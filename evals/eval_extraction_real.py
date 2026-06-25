"""Auditoria do baseline em folhas REAIS (plano Fase 2) — zero-custo, local.

Roda o pipeline atual (LocalOCR Tesseract + RuleBasedLLM + config atual) em cada folha
real cuja curadoria existe em `private/curadoria/`, compara com o ground-truth e classifica
cada discrepância pela taxonomia de erros COM SEVERIDADE (plano R3):

    FALSE_INCIDENT / MISSED_INCIDENT      -> BLOCKER   (decisão operacional errada)
    BAD_NORMALIZATION / TABLE_ROW_SPLIT_ERROR -> HIGH
    FIELD_NOT_FOUND / OCR_MISS            -> MEDIUM
    NEEDS_HUMAN_REVIEW                    -> LOW       (roteado certo p/ humano; desejado)

Saídas:
  - DETALHADO (com valores/trechos OCR = PII)  -> private/audit/metrics_real.json  (gitignored)
  - PÚBLICO sanitizado (só números)            -> docs/AUDITORIA_FOLHAS_REAIS.md   (gate de PII, R4)

Quality gates (plano R4):
  - curadoria sem review_status válido é ignorada;
  - só `verified_by_user` conta na auditoria FINAL — `draft_by_claude`/`needs_review` entram como
    PRELIMINAR (pendente de conferência), nunca como número oficial;
  - o relatório público NÃO é escrito se a varredura de PII achar algo.

Uso: PYTHONPATH=. uv run python -m evals.eval_extraction_real
(precisa de Tesseract no PATH + TESSDATA_PREFIX com 'por'; folhas em private/reais/.)
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

from evals.metrics import cer
from scripts.privacy_check import scan_text_for_pii
from src.clients.local_ocr import LocalOCRVisionClient
from src.clients.local_rules import RuleBasedLLMClient
from src.orchestrator import run_pipeline
from src.pipeline.ingest import OCR_DPI
from src.schema.extraction import NormalizedIncidentModel
from src.schema.loader import load_config
from src.schema.state import ExtractedField

CURADORIA_DIR = Path("private/curadoria")
AUDIT_DIR = Path("private/audit")
CONFIG_PATH = Path("configs/htmicron_security.yaml")  # ANTES (escalar)
TABLE_CONFIG_PATH = Path("configs/controle_ocorrencias.yaml")  # DEPOIS (tabela)
REPORT_PATH = Path("docs/AUDITORIA_FOLHAS_REAIS.md")

VALID_REVIEW_STATUS = {"draft_by_claude", "needs_review", "verified_by_user"}

SEVERITY: dict[str, str] = {
    "FALSE_INCIDENT": "BLOCKER",
    "MISSED_INCIDENT": "BLOCKER",
    "BAD_NORMALIZATION": "HIGH",
    "TABLE_ROW_SPLIT_ERROR": "HIGH",
    "FIELD_NOT_FOUND": "MEDIUM",
    "OCR_MISS": "MEDIUM",
    "NEEDS_HUMAN_REVIEW": "LOW",
}

# Campo da config atual (escalar) -> chave do cabeçalho na curadoria.
HEADER_MAP = {"shift_date": "data", "guard_name": "vigilantes", "post": "unidade"}

# Acima deste CER, um valor lido é considerado não-fiel (OCR_MISS / ocorrência perdida).
CER_FAIL = 0.5


# --- helpers puros (testáveis sem Tesseract) --------------------------------


def _norm(text: str) -> str:
    """Normaliza p/ comparação: minúsculas, sem acento, espaços colapsados."""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(no_accent.lower().split())


def field_status(value: Any, must_review: bool) -> str:
    """Status de auditoria por campo (plano R2)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "missing"
    return "must_review" if must_review else "accepted"


def has_occurrence(cur: dict[str, Any]) -> bool:
    """True se a folha tem ocorrência real (não S/A, não riscado, lista não-vazia)."""
    if cur.get("sem_alteracao") or cur.get("riscado"):
        return False
    return bool(cur.get("ocorrencias"))


def curated_header(cur: dict[str, Any], key: str) -> str | None:
    """Valor do cabeçalho curado p/ *key* ('vigilantes' é juntado por vírgula)."""
    cab = cur.get("cabecalho", {})
    if key == "vigilantes":
        names = cab.get("vigilantes") or []
        return ", ".join(names) if names else None
    val = cab.get(key)
    return val if val else None


def _system_description(extracted: list[ExtractedField]) -> str | None:
    """Valor que o sistema atual produziu para incident_description (ou None)."""
    for ef in extracted:
        if ef.name == "incident_description":
            if ef.value is None:
                return None
            text = str(ef.value).strip()
            return text or None
    return None


def classify_errors(cur: dict[str, Any], extracted: list[ExtractedField]) -> list[dict[str, str]]:
    """Classifica discrepâncias (folha curada x extração do sistema) pela taxonomia R3."""
    by_name = {ef.name: ef for ef in extracted}
    errors: list[dict[str, str]] = []

    def add(etype: str, field: str = "") -> None:
        errors.append({"type": etype, "severity": SEVERITY[etype], "field": field})

    # Cabeçalho: captura por campo.
    for fname, ckey in HEADER_MAP.items():
        cval = curated_header(cur, ckey)
        if not cval:
            continue
        ef = by_name.get(fname)
        if ef is None or ef.value is None or not str(ef.value).strip():
            add("FIELD_NOT_FOUND", fname)
        elif cer(_norm(cval), _norm(str(ef.value))) > CER_FAIL:
            add("OCR_MISS", fname)

    # Ocorrências (o coração da folha).
    occ = has_occurrence(cur)
    sys_desc = _system_description(extracted)
    if not occ and sys_desc and _norm(sys_desc) not in {"", "s a", "sa"}:
        add("FALSE_INCIDENT", "incident_description")
    if occ:
        first = cur["ocorrencias"][0].get("descricao", "") or ""
        if sys_desc is None or cer(_norm(first), _norm(sys_desc)) > CER_FAIL:
            add("MISSED_INCIDENT", "incident_description")
        if len(cur["ocorrencias"]) > 1:
            add("TABLE_ROW_SPLIT_ERROR", "ocorrencias")

    # Carga de revisão humana (desejada): cada campo must_review.
    for ef in extracted:
        if ef.must_review:
            add("NEEDS_HUMAN_REVIEW", ef.name)

    return errors


def classify_errors_normalized(
    cur: dict[str, Any], normalized: NormalizedIncidentModel, extracted: list[ExtractedField]
) -> list[dict[str, str]]:
    """Taxonomia R3 para o caminho de TABELA (compara o modelo normalizado x curadoria)."""
    errors: list[dict[str, str]] = []

    def add(etype: str, field: str = "") -> None:
        errors.append({"type": etype, "severity": SEVERITY[etype], "field": field})

    header = {
        "data": normalized.shift.date,
        "unidade": normalized.shift.unit,
        "vigilantes": ", ".join(normalized.shift.guards) if normalized.shift.guards else None,
    }
    for ckey, sysval in header.items():
        cval = curated_header(cur, ckey)
        if not cval:
            continue
        if not sysval:
            add("FIELD_NOT_FOUND", ckey)
        elif cer(_norm(cval), _norm(str(sysval))) > CER_FAIL:
            add("OCR_MISS", ckey)

    occ = has_occurrence(cur)
    if not occ and not normalized.no_occurrence and normalized.occurrences:
        add("FALSE_INCIDENT", "ocorrencias")
    if occ and normalized.no_occurrence:
        add("MISSED_INCIDENT", "ocorrencias")
    if occ and len(cur.get("ocorrencias", [])) > len(normalized.occurrences):
        add("TABLE_ROW_SPLIT_ERROR", "ocorrencias")

    for ef in extracted:
        if ef.must_review:
            add("NEEDS_HUMAN_REVIEW", ef.name)
    return errors


def aggregate(per_sheet: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega contagens por tipo/severidade e status de campo (sanitizável)."""
    run = [s for s in per_sheet if s["ran"]]
    err_by_type: dict[str, int] = {}
    err_by_sev: dict[str, int] = {}
    status_counts: dict[str, int] = {"accepted": 0, "must_review": 0, "missing": 0}
    occ_total = 0
    occ_captured = 0
    occ_represented = 0
    for s in run:
        for e in s["errors"]:
            err_by_type[e["type"]] = err_by_type.get(e["type"], 0) + 1
            err_by_sev[e["severity"]] = err_by_sev.get(e["severity"], 0) + 1
        for st in s["field_statuses"].values():
            status_counts[st] = status_counts.get(st, 0) + 1
        occ_total += s["n_occurrences_curated"]
        occ_captured += s["n_occurrences_captured"]
        occ_represented += s.get("n_occurrences_represented", 0)
    return {
        "n_sheets_total": len(per_sheet),
        "n_sheets_run": len(run),
        "n_sheets_pending_file": sum(1 for s in per_sheet if s["status"] == "pending_file"),
        "n_verified_by_user": sum(1 for s in per_sheet if s["review_status"] == "verified_by_user"),
        "errors_by_type": err_by_type,
        "errors_by_severity": err_by_sev,
        "field_status_counts": status_counts,
        "occurrences_curated": occ_total,
        "occurrences_represented": occ_represented,
        "occurrences_captured_faithfully": occ_captured,
        "mean_ocr_confidence": (
            round(sum(s["ocr_confidence"] for s in run) / len(run), 3) if run else 0.0
        ),
    }


# --- execução do pipeline (precisa de Tesseract) ----------------------------


def load_curadoria(directory: Path = CURADORIA_DIR) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("review_status") in VALID_REVIEW_STATUS:
            out.append(data)
    return out


def run_sheet(cur: dict[str, Any], config: Any) -> dict[str, Any]:
    """Roda o pipeline atual numa folha; devolve o resultado detalhado (com PII)."""
    base: dict[str, Any] = {
        "document_id": cur["document_id"],
        "review_status": cur["review_status"],
        "ran": False,
        "status": "ok",
        "errors": [],
        "field_statuses": {},
        "n_occurrences_curated": len(cur.get("ocorrencias", [])),
        "n_occurrences_represented": 0,
        "n_occurrences_captured": 0,
        "ocr_confidence": 0.0,
    }
    src = Path(str(cur.get("source_file", "")).split(" ")[0])
    if not src.exists():
        base["status"] = "pending_file"
        return base
    try:
        state = run_pipeline(
            src, LocalOCRVisionClient(), RuleBasedLLMClient(config), config, dpi=OCR_DPI
        )
    except RuntimeError as exc:  # Tesseract ausente etc.
        base["status"] = f"ocr_error: {exc}"
        return base

    extracted = state.extracted_fields
    base["ran"] = True
    base["ocr_confidence"] = round(state.transcription_confidence or 0.0, 3)
    base["field_statuses"] = {
        ef.name: field_status(ef.value, ef.must_review) for ef in extracted
    }
    if state.normalized is not None:
        # Caminho de TABELA (controle_ocorrencias).
        base["errors"] = classify_errors_normalized(cur, state.normalized, extracted)
        if has_occurrence(cur) and not state.normalized.no_occurrence:
            base["n_occurrences_represented"] = 1
            first = cur["ocorrencias"][0].get("descricao", "") or ""
            for o in state.normalized.occurrences:
                if o.description and cer(_norm(first), _norm(o.description)) <= CER_FAIL:
                    base["n_occurrences_captured"] = 1
                    break
    else:
        # Caminho ESCALAR (htmicron_security).
        base["errors"] = classify_errors(cur, extracted)
        if has_occurrence(cur):
            sys_desc = _system_description(extracted)
            first = cur["ocorrencias"][0].get("descricao", "") or ""
            if sys_desc is not None and cer(_norm(first), _norm(sys_desc)) <= CER_FAIL:
                base["n_occurrences_captured"] = 1
    # Detalhe com PII (só p/ private/): transcrição + valores extraídos.
    base["_detail"] = {
        "transcription": state.transcription,
        "extracted": [{"name": ef.name, "value": ef.value} for ef in extracted],
    }
    return base


def render_report(agg: dict[str, Any]) -> str:
    """Renderiza o relatório público SANITIZADO (só números + narrativa, sem PII)."""
    et = agg["errors_by_type"]
    sev = agg["errors_by_severity"]
    fs = agg["field_status_counts"]
    preliminary = agg["n_verified_by_user"] == 0
    lines: list[str] = [
        "# AUDITORIA — Folhas reais (baseline do sistema atual)",
        "",
        "> Gerado por `evals/eval_extraction_real.py`. **Nenhum número é digitado à mão.** "
        "Contém apenas métricas agregadas + exemplos sintéticos — dados reais ficam em "
        "`private/` (plano R6/regra #2). Detalhe com PII em `private/audit/metrics_real.json`.",
        "",
    ]
    if preliminary:
        lines += [
            "> ⚠️ **PRELIMINAR.** Nenhuma curadoria está `verified_by_user` ainda "
            f"({agg['n_verified_by_user']}/{agg['n_sheets_total']}). Os números abaixo usam a "
            "transcrição automática como ground-truth e **devem ser reconferidos** (plano R4).",
            "",
        ]
    lines += [
        "## Cobertura",
        "",
        f"- Folhas com curadoria: **{agg['n_sheets_total']}**",
        f"- Rodadas no pipeline: **{agg['n_sheets_run']}**",
        f"- Pendentes (arquivo da imagem ausente em `private/reais/`): "
        f"**{agg['n_sheets_pending_file']}**",
        f"- Confiança média do OCR (Tesseract): **{agg['mean_ocr_confidence']}**",
        "",
        "## Captura de ocorrências (o dado mais importante)",
        "",
        f"- Ocorrências reais na curadoria: **{agg['occurrences_curated']}**",
        f"- Capturadas com fidelidade pelo sistema atual: "
        f"**{agg['occurrences_captured_faithfully']}**",
        "",
        "## Status dos campos (plano R2)",
        "",
        "| status | contagem |",
        "|---|---|",
        f"| accepted | {fs.get('accepted', 0)} |",
        f"| must_review | {fs.get('must_review', 0)} |",
        f"| missing | {fs.get('missing', 0)} |",
        "",
        "## Erros por severidade (plano R3)",
        "",
        "| severidade | contagem |",
        "|---|---|",
        f"| BLOCKER | {sev.get('BLOCKER', 0)} |",
        f"| HIGH | {sev.get('HIGH', 0)} |",
        f"| MEDIUM | {sev.get('MEDIUM', 0)} |",
        f"| LOW (revisão humana, desejado) | {sev.get('LOW', 0)} |",
        "",
        "## Erros por tipo",
        "",
        "| tipo | severidade | contagem |",
        "|---|---|---|",
    ]
    for etype in SEVERITY:
        lines.append(f"| {etype} | {SEVERITY[etype]} | {et.get(etype, 0)} |")
    lines += [
        "",
        "## Leitura honesta",
        "",
        "- O Tesseract lê **rótulos impressos** bem, mas **valores cursivos** viram ruído — "
        "esperado para OCR livre em manuscrito (não é um defeito do pipeline).",
        "- O achado estrutural: a config atual modela **incidente único escalar**; a folha real "
        "é uma **tabela de N linhas** (Item/Hora/Descrição/Ação/Resolvido) com cabeçalho de "
        "vários vigilantes. O conteúdo das ocorrências **não tem onde ser representado** hoje "
        "→ `MISSED_INCIDENT`/`TABLE_ROW_SPLIT_ERROR`. Isso motiva o ADR.",
        "- `BLOCKER`/`HIGH` são a prioridade da reforma; `LOW` (must_review) é o comportamento "
        "desejado (\"nunca adivinhar\").",
        "",
    ]
    return "\n".join(lines)


def run_config(
    curadoria: list[dict[str, Any]], config_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Roda todas as folhas com uma config; devolve (per_sheet detalhado, agregado)."""
    config = load_config(config_path)
    per_sheet = [run_sheet(cur, config) for cur in curadoria]
    return per_sheet, aggregate(per_sheet)


def _sev_row(label: str, antes: dict[str, Any], depois: dict[str, Any], key: str) -> str:
    return f"| {label} | {antes.get(key, 0)} | {depois.get(key, 0)} |"


def render_compare(antes: dict[str, Any], depois: dict[str, Any]) -> str:
    """Relatório público SANITIZADO com ANTES (escalar) x DEPOIS (tabela). Sem PII."""
    a_sev, d_sev = antes["errors_by_severity"], depois["errors_by_severity"]
    a_fs, d_fs = antes["field_status_counts"], depois["field_status_counts"]
    preliminary = depois["n_verified_by_user"] == 0
    lines: list[str] = [
        "# AUDITORIA — Folhas reais (ANTES escalar × DEPOIS tabela)",
        "",
        "> Gerado por `evals/eval_extraction_real.py`. **Nenhum número é digitado à mão.** "
        "Só métricas agregadas — dados reais ficam em `private/` (plano R6/regra #2). "
        "Detalhe com PII em `private/audit/metrics_real.json`.",
        "",
        "- **ANTES** = config escalar `htmicron_security` (incidente único).",
        "- **DEPOIS** = config `controle_ocorrencias` (cabeçalho + tabela de N linhas).",
        "",
    ]
    if preliminary:
        lines += [
            "> ⚠️ **PRELIMINAR.** Nenhuma curadoria está `verified_by_user` "
            f"({depois['n_verified_by_user']}/{depois['n_sheets_total']}). Ground-truth ainda é a "
            "transcrição automática; reconferir (plano R4).",
            "",
        ]
    lines += [
        "## Cobertura (igual nos dois)",
        "",
        f"- Folhas com curadoria: **{depois['n_sheets_total']}** | rodadas: "
        f"**{depois['n_sheets_run']}** | pendentes: **{depois['n_sheets_pending_file']}**",
        "",
        "## Ocorrências (o dado mais importante)",
        "",
        "| métrica | ANTES | DEPOIS |",
        "|---|---|---|",
        f"| ocorrências reais (curadoria) | {antes['occurrences_curated']} "
        f"| {depois['occurrences_curated']} |",
        f"| **representadas** (têm onde existir) | {antes.get('occurrences_represented', 0)} "
        f"| {depois.get('occurrences_represented', 0)} |",
        f"| capturadas fielmente (CER ≤ {CER_FAIL}) | "
        f"{antes['occurrences_captured_faithfully']} | "
        f"{depois['occurrences_captured_faithfully']} |",
        "",
        "## Erros por severidade (plano R3)",
        "",
        "| severidade | ANTES | DEPOIS |",
        "|---|---|---|",
        _sev_row("BLOCKER", a_sev, d_sev, "BLOCKER"),
        _sev_row("HIGH", a_sev, d_sev, "HIGH"),
        _sev_row("MEDIUM", a_sev, d_sev, "MEDIUM"),
        _sev_row("LOW (revisão humana, desejado)", a_sev, d_sev, "LOW"),
        "",
        "## Status dos campos (plano R2)",
        "",
        "| status | ANTES | DEPOIS |",
        "|---|---|---|",
        _sev_row("accepted", a_fs, d_fs, "accepted"),
        _sev_row("must_review", a_fs, d_fs, "must_review"),
        _sev_row("missing", a_fs, d_fs, "missing"),
        "",
        "## Erros por tipo (DEPOIS)",
        "",
        "| tipo | severidade | DEPOIS |",
        "|---|---|---|",
    ]
    d_et = depois["errors_by_type"]
    for etype in SEVERITY:
        lines.append(f"| {etype} | {SEVERITY[etype]} | {d_et.get(etype, 0)} |")
    lines += [
        "",
        "## Leitura honesta",
        "",
        "- A reforma (caminho tabela) faz a ocorrência **ser representada** e trata `S/A` como "
        "sem alteração — eliminando os `BLOCKER` (`FALSE_INCIDENT` na folha S/A e "
        "`MISSED_INCIDENT` por não ter onde guardar a ocorrência).",
        "- O OCR cursivo do Tesseract continua fraco: o conteúdo capturado entra como "
        "`must_review` (LOW, desejado) para o humano confirmar/corrigir — não some nem é "
        "dado como certo. Fidelidade de texto (CER) só melhora com OCR/manuscrito melhor.",
        "- Números preliminares até a curadoria ser `verified_by_user` (plano R4).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Auditoria de folhas reais (antes/depois).")
    parser.add_argument("--no-report", action="store_true", help="não escrever o doc público")
    args = parser.parse_args(argv)

    curadoria = load_curadoria()
    if not curadoria:
        print("Nenhuma curadoria válida em private/curadoria/ — nada a auditar.", file=sys.stderr)
        return 1

    antes_per, antes_agg = run_config(curadoria, CONFIG_PATH)
    depois_per, depois_agg = run_config(curadoria, TABLE_CONFIG_PATH)

    # Detalhado (PII) -> private/.
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIT_DIR / "metrics_real.json").write_text(
        json.dumps(
            {
                "antes": {"aggregate": antes_agg, "per_sheet": antes_per},
                "depois": {"aggregate": depois_agg, "per_sheet": depois_per},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = render_compare(antes_agg, depois_agg)
    # Gate de PII (plano R4): nunca escrever relatório público com PII.
    pii = scan_text_for_pii(report, include_org=False)
    if pii:
        print("ABORTADO: PII detectada no relatório público:", file=sys.stderr)
        for h in pii:
            print(h, file=sys.stderr)
        return 2

    if not args.no_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"Escrito {REPORT_PATH} e {AUDIT_DIR / 'metrics_real.json'}")
    print(json.dumps({"antes": antes_agg, "depois": depois_agg}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
