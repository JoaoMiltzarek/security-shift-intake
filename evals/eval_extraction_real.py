"""Auditoria/medição do pipeline em folhas REAIS — zero-custo, local.

Dois modos (docs/EVAL_PROTOCOL.md é o contrato normativo das fórmulas e gates):

1. **Instrumentado (default)** — roda o pipeline (config de TABELA) com o leitor
   escolhido (`--vision local_ocr|paddle_ocr|local_vlm|mock`, `--dpi`, `--n`) sobre cada folha
   com curadoria em `private/curadoria/`, e registra por folha as métricas do
   protocolo: `parse_table_success`, esforço humano (`estimated_chars_to_type`,
   `prefilled_but_wrong_count`, `blank_field_count`, `illegible_token_count`),
   probe de repairability (`repairable_ratio`, `missing_count`), `elapsed_sec`,
   `ocr_quality` e `confidence_source` (lido do schema, nunca inferido). Erro do
   leitor (ex.: Ollama offline) NUNCA derruba a rodada: a folha sai
   `available:false` com motivo (invariante EVAL_PROTOCOL §9).
   Saídas: detalhado (PII) -> private/audit/eval_real_detailed_{reader}_dpi{dpi}.json
           público whitelist -> docs/eval_real_summary.json (gate de PII em 2ª camada)

2. **`--legacy-compare`** — o compare ANTES (escalar) × DEPOIS (tabela) original,
   com a taxonomia R3, que gera docs/AUDITORIA_FOLHAS_REAIS.md. Inalterado.

`--compare A.json B.json` calcula a comparação PAREADA por campo entre duas rodadas
detalhadas (baseline × VLM) — o formato que sustenta o gate G1 com n pequeno.

Quality gates: curadoria sem review_status válido é ignorada; só `verified_by_user`
conta como número oficial (senão PRELIMINAR/DIRECIONAL, EVAL_PROTOCOL §4); relatório
público não é escrito se a varredura de PII achar algo.

Uso: PYTHONPATH=. uv run python -m evals.eval_extraction_real --vision local_vlm --dpi 150
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import httpx

from evals.metrics import cer, levenshtein
from scripts.privacy_check import scan_text_for_pii
from src.api.gate import DraftNotReviewableError, assert_reviewable
from src.clients.base import VisionClient
from src.clients.factory import get_vision_client
from src.clients.local_ocr import LocalOCRVisionClient
from src.clients.local_rules import RuleBasedLLMClient
from src.clients.local_vlm import _TRANSCRIPTION_PROMPT
from src.clients.paddle_ocr import PADDLE_DETECTION_MODEL, PADDLE_RECOGNITION_MODEL
from src.clients.settings import get_vlm_base_url, get_vlm_model
from src.orchestrator import run_pipeline
from src.paths import PRIVATE_ROOT, REPO_ROOT
from src.pipeline.ingest import OCR_DPI
from src.pipeline.outputs import export_blockers
from src.schema.config import ReportConfig
from src.schema.extraction import NormalizedIncidentModel
from src.schema.loader import load_config
from src.schema.state import ExtractedField

CURADORIA_DIR = PRIVATE_ROOT / "curadoria"
AUDIT_DIR = PRIVATE_ROOT / "audit"
CONFIG_PATH = REPO_ROOT / "configs" / "htmicron_security.yaml"  # ANTES (escalar, legado)
TABLE_CONFIG_PATH = REPO_ROOT / "configs" / "controle_ocorrencias.yaml"  # DEPOIS (tabela)
REPORT_PATH = REPO_ROOT / "docs" / "AUDITORIA_FOLHAS_REAIS.md"
SUMMARY_PATH = REPO_ROOT / "docs" / "eval_real_summary.json"

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

# Campo da config atual (escalar) -> chave do cabeçalho na curadoria (legado).
HEADER_MAP = {"shift_date": "data", "guard_name": "vigilantes", "post": "unidade"}

# Mapping normativo do cabeçalho da config de TABELA (EVAL_PROTOCOL §1):
# campo da config -> chave na curadoria. O lado normalizado vive em
# _normalized_header_value(). Campo novo na config entra na régua ganhando uma
# linha aqui — nunca um `if` solto.
HEADER_TO_CURATED = {"data_turno": "data", "vigilantes": "vigilantes", "unidade": "unidade"}

# Acima deste CER, um valor lido é considerado não-fiel (OCR_MISS / campo errado).
CER_FAIL = 0.5

# Tolerância de |linhas curadas - linhas normalizadas| no parse_table_success (§2.1).
ROW_COUNT_TOLERANCE = 0

# Mínimos de honestidade estatística (EVAL_PROTOCOL §4).
MIN_VERIFIED_SHEETS = 10

# Motivos de falha publicados são truncados (whitelist §7: sem valores, sem folhas).
_REASON_MAX_CHARS = 160

# Chaves por folha que entram no público — whitelist POR CONSTRUÇÃO (§7): o dict
# público nasce só destas chaves; nunca é o detalhado com campos removidos.
_PUBLIC_SHEET_KEYS = (
    "parse_table_success",
    "must_review_count",
    "missing_count",
    "repairable_ratio",
    "estimated_chars_to_type",
    "prefilled_but_wrong_count",
    "blank_field_count",
    "illegible_token_count",
    "campos_corrigidos_por_folha",
    "n_fields_compared",
    "elapsed_sec",
    "ocr_quality",
    "confidence_source",
    "available",
)


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


def _required_scalars(config: ReportConfig) -> list[str]:
    """Campos escalares required:true da config — o header_minimum do protocolo §2.1."""
    return [f.name for f in config.fields if f.type != "table" and f.required]


def _normalized_header_value(normalized: NormalizedIncidentModel, name: str) -> str | None:
    """Lado normalizado do mapping do protocolo §1 (config -> NormalizedShift)."""
    if name == "data_turno":
        return normalized.shift.date
    if name == "vigilantes":
        return ", ".join(normalized.shift.guards) if normalized.shift.guards else None
    if name == "unidade":
        return normalized.shift.unit
    return None  # sem linha no mapping §1 → conta como ausente (nunca inventa)


def parse_table_success(
    cur: dict[str, Any],
    normalized: NormalizedIncidentModel,
    config: ReportConfig,
    tolerance: int = ROW_COUNT_TOLERANCE,
) -> bool:
    """Fórmula §2.1: S/A×ocorrência correto + header mínimo + contagem de linhas."""
    occ = has_occurrence(cur)
    expected_disposition = "present" if occ else "none"
    if normalized.disposition != expected_disposition:
        return False
    for name in _required_scalars(config):
        if not _normalized_header_value(normalized, name):
            return False
    expected = len(cur.get("ocorrencias", [])) if occ else 0
    if abs(expected - len(normalized.occurrences)) > tolerance:
        return False
    # Representação da 1ª ocorrência (§2.1.4): com ocorrência, precisa haver linha.
    return not (occ and not normalized.occurrences)


def comparable_fields(
    cur: dict[str, Any], normalized: NormalizedIncidentModel, config: ReportConfig
) -> dict[str, tuple[str | None, str | None]]:
    """Campos comparáveis (§1): escalares do mapping + descrição da 1ª ocorrência.

    Retorna nome -> (valor curado, valor do sistema). Limitação declarada no
    protocolo: multi-ocorrência mede só cabeçalho + 1ª ocorrência.
    """
    out: dict[str, tuple[str | None, str | None]] = {}
    for name in _required_scalars(config):
        ckey = HEADER_TO_CURATED.get(name)
        if ckey is None:
            continue  # sem linha no mapping §1 → fora da régua (nunca adivinhar)
        out[name] = (curated_header(cur, ckey), _normalized_header_value(normalized, name))
    if has_occurrence(cur):
        first = cur["ocorrencias"][0].get("descricao") or None
        sys_first = normalized.occurrences[0].description if normalized.occurrences else None
        out["ocorrencia_1_descricao"] = (first, sys_first)
    return out


def effort_metrics(comp: dict[str, tuple[str | None, str | None]]) -> dict[str, Any]:
    """Fórmulas §2.2 — esforço humano por folha, a partir dos campos comparáveis."""
    field_compare: dict[str, dict[str, Any]] = {}
    chars_total = 0
    wrong = 0
    blank = 0
    for name, (cur_v, sys_v) in comp.items():
        if cur_v is None or not str(cur_v).strip():
            continue  # sem ground-truth curado → fora da régua de esforço
        c = _norm(str(cur_v))
        s = _norm(str(sys_v)) if (sys_v is not None and str(sys_v).strip()) else ""
        if not s:
            blank += 1
            cost = len(c)
            field_cer = 1.0
        else:
            cost = levenshtein(s, c)
            field_cer = cer(c, s)
            if field_cer > CER_FAIL:
                wrong += 1
        chars_total += cost
        field_compare[name] = {
            "cer": round(field_cer, 3),
            "correct": bool(s) and field_cer <= CER_FAIL,
            "chars_to_type": cost,
            "system_blank": not s,
        }
    return {
        "estimated_chars_to_type": chars_total,
        "prefilled_but_wrong_count": wrong,
        "blank_field_count": blank,
        "campos_corrigidos_por_folha": wrong + blank,
        "n_fields_compared": len(field_compare),
        "field_compare": field_compare,
    }


def repairable_ratio(fields: list[ExtractedField]) -> float | None:
    """Probe §2.3: fração dos must_review com geometria (bbox+page). 0/0 -> None."""
    pending = [f for f in fields if f.must_review]
    if not pending:
        return None
    with_geo = sum(1 for f in pending if f.bbox is not None and f.page is not None)
    return round(with_geo / len(pending), 3)


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
    if not occ and normalized.disposition == "present":
        add("FALSE_INCIDENT", "ocorrencias")
    if occ and normalized.disposition == "none":
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


# --- metadados forenses da rodada (EVAL_PROTOCOL §7) -------------------------


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=REPO_ROOT
        ).strip()
    except Exception:  # noqa: BLE001 — forense best-effort, nunca derruba a rodada
        return "unknown"


def _model_tag(reader: str) -> str:
    """Tag+digest do modelo do leitor (best-effort via /api/tags do Ollama)."""
    if reader == "local_ocr":
        return "tesseract"
    if reader == "mock":
        return "mock"
    if reader == "paddle_ocr":
        versions: dict[str, str] = {}
        for package in ("paddleocr", "paddlepaddle"):
            try:
                versions[package] = importlib_metadata.version(package)
            except importlib_metadata.PackageNotFoundError:
                versions[package] = "not-installed"
        return (
            f"{PADDLE_DETECTION_MODEL} + {PADDLE_RECOGNITION_MODEL}; device=cpu; "
            f"paddleocr={versions['paddleocr']}; paddlepaddle={versions['paddlepaddle']}"
        )
    model = get_vlm_model()
    root = get_vlm_base_url().split("/v1")[0]
    try:
        resp = httpx.get(f"{root}/api/tags", timeout=5)
        for m in resp.json().get("models", []):
            if model in {m.get("name"), m.get("model")}:
                digest = str(m.get("digest", ""))[:19]
                return f"{model} {digest}".strip()
    except Exception:  # noqa: BLE001 — best-effort; 'unknown' é a resposta honesta
        pass
    return f"{model} unknown"


def run_metadata(reader: str, dpi: int) -> dict[str, Any]:
    """Metadados que tornam a rodada re-executável (hash do prompt, modelo, commit)."""
    prompt_hash = (
        hashlib.sha256(_TRANSCRIPTION_PROMPT.encode("utf-8")).hexdigest()
        if reader == "local_vlm"
        else None
    )
    return {
        "reader": reader,
        "model": _model_tag(reader),
        "dpi": dpi,
        "prompt_sha256": prompt_hash,
        "git_commit": _git_commit(),
        # Compacto (sem ':') para não colidir com o padrão de hora do gate de PII.
        "timestamp": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    }


# --- execução do pipeline (precisa de leitor real p/ folhas reais) -----------


def load_curadoria(
    directory: Path = CURADORIA_DIR, valid_status: set[str] = VALID_REVIEW_STATUS
) -> list[dict[str, Any]]:
    """Carrega gabaritos aceitos por *valid_status* (default: só curadoria REAL).

    O eval sintético (PR-D6) chama com valid_status={"synthetic_ground_truth"} —
    opt-in explícito; o eval real segue ignorando verdade gerada por construção
    (docs/CURADORIA_FORMATO.md / DATASET_CONTRACT.md §2.2).
    """
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("review_status") in valid_status:
            out.append(data)
    return out


def run_sheet(
    cur: dict[str, Any],
    config: Any,
    vision: VisionClient | None = None,
    dpi: int = OCR_DPI,
) -> dict[str, Any]:
    """Roda o pipeline numa folha; devolve o resultado detalhado (com PII).

    Erro do leitor (RuntimeError: Tesseract ausente, Ollama offline, resposta vazia
    do VLM) NUNCA propaga: a folha sai `available:false` com o motivo — a rodada e
    as outras folhas continuam (EVAL_PROTOCOL §8/§9).
    """
    base: dict[str, Any] = {
        "document_id": cur["document_id"],
        "review_status": cur["review_status"],
        "ran": False,
        "available": False,
        "reason": None,
        "status": "ok",
        "errors": [],
        "field_statuses": {},
        "n_occurrences_curated": len(cur.get("ocorrencias", [])),
        "n_occurrences_represented": 0,
        "n_occurrences_captured": 0,
        "ocr_confidence": 0.0,
    }
    src = Path(str(cur.get("source_file", "")))
    if not src.exists():
        base["status"] = "pending_file"
        base["reason"] = "pending_file"
        return base
    reader = vision if vision is not None else LocalOCRVisionClient()
    started = time.monotonic()
    try:
        state = run_pipeline(src, reader, RuleBasedLLMClient(config), config, dpi=dpi)
    except RuntimeError as exc:  # leitor indisponível/falha — nunca mata a rodada
        base["status"] = f"reader_error: {exc}"
        base["reason"] = str(exc)[:_REASON_MAX_CHARS]
        return base
    elapsed = time.monotonic() - started

    # Preserve the operational outcomes of the PipelineState that was actually
    # executed. Safety evals must not infer these gates from disposition or replay
    # a second pipeline, because either shortcut can hide a disconnected validator.
    try:
        assert_reviewable(state)
    except DraftNotReviewableError:
        operational_approvable = False
    else:
        operational_approvable = True
    operational_export_blockers = export_blockers(state)
    base.update(
        {
            "operational_approvable": operational_approvable,
            "operational_exportable": not operational_export_blockers,
            "operational_export_blocker_count": len(operational_export_blockers),
            "normalized_disposition": (
                state.normalized.disposition if state.normalized is not None else None
            ),
        }
    )

    extracted = state.extracted_fields
    base["ran"] = True
    base["available"] = True
    base["elapsed_sec"] = round(elapsed, 2)
    base["ocr_confidence"] = round(state.transcription_confidence or 0.0, 3)
    base["ocr_quality"] = state.ocr_quality
    base["confidence_source"] = state.transcription_confidence_source
    base["field_statuses"] = {
        ef.name: field_status(ef.value, ef.must_review) for ef in extracted
    }
    base["must_review_count"] = len(state.must_review_fields)
    base["missing_count"] = sum(
        1 for st in base["field_statuses"].values() if st == "missing"
    )
    base["illegible_token_count"] = (state.transcription or "").count("[ilegível]")
    base["repairable_ratio"] = repairable_ratio(extracted)
    if state.normalized is not None:
        # Caminho de TABELA (controle_ocorrencias) — as métricas do protocolo.
        base["errors"] = classify_errors_normalized(cur, state.normalized, extracted)
        base["parse_table_success"] = parse_table_success(cur, state.normalized, config)
        base.update(effort_metrics(comparable_fields(cur, state.normalized, config)))
        if has_occurrence(cur) and state.normalized.disposition == "present":
            base["n_occurrences_represented"] = 1
            first = cur["ocorrencias"][0].get("descricao", "") or ""
            for o in state.normalized.occurrences:
                if o.description and cer(_norm(first), _norm(o.description)) <= CER_FAIL:
                    base["n_occurrences_captured"] = 1
                    break
    else:
        # Caminho ESCALAR (htmicron_security) — só a taxonomia legada.
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


def run_config(
    curadoria: list[dict[str, Any]], config_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Roda todas as folhas com uma config; devolve (per_sheet detalhado, agregado)."""
    config = load_config(config_path)
    per_sheet = [run_sheet(cur, config) for cur in curadoria]
    return per_sheet, aggregate(per_sheet)


# --- público whitelist + pareado (EVAL_PROTOCOL §2.5/§7) ---------------------


def build_public_run(meta: dict[str, Any], per_sheet: list[dict[str, Any]]) -> dict[str, Any]:
    """Entrada pública de UMA rodada, construída POR WHITELIST (nunca subtração).

    Folhas viram `sheet_N` na ordem de `document_id` — nenhum id/caminho/valor sai.
    """
    ordered = sorted(per_sheet, key=lambda s: str(s.get("document_id", "")))
    pub_sheets: list[dict[str, Any]] = []
    for i, s in enumerate(ordered, start=1):
        entry: dict[str, Any] = {"sheet": f"sheet_{i}"}
        for key in _PUBLIC_SHEET_KEYS:
            entry[key] = s.get(key)
        if not s.get("available"):
            entry["reason"] = str(s.get("reason") or s.get("status") or "")[:_REASON_MAX_CHARS]
        pub_sheets.append(entry)

    ran = [s for s in ordered if s.get("ran")]
    with_pts = [s for s in ran if s.get("parse_table_success") is not None]
    success = sum(1 for s in with_pts if s["parse_table_success"])
    rep_num = 0.0
    rep_den = 0
    for s in ran:
        rr = s.get("repairable_ratio")
        mr = s.get("must_review_count") or 0
        if rr is not None and mr:
            rep_num += rr * mr
            rep_den += mr
    n_verified = sum(1 for s in per_sheet if s.get("review_status") == "verified_by_user")
    elapsed = [s["elapsed_sec"] for s in ran if s.get("elapsed_sec") is not None]
    return {
        **meta,
        "n_sheets": len(per_sheet),
        "n_sheets_ran": len(ran),
        "n_verified_by_user": n_verified,
        "n_fields_compared": sum(s.get("n_fields_compared") or 0 for s in ran),
        # DIRECIONAL enquanto n_verified < 10 (EVAL_PROTOCOL §4) — impresso, não escondido.
        "directional": n_verified < MIN_VERIFIED_SHEETS,
        "aggregate": {
            "parse_table_success_rate": (
                round(success / len(with_pts), 3) if with_pts else None
            ),
            "parse_table_success_count": success,
            "estimated_chars_to_type_total": sum(
                s.get("estimated_chars_to_type") or 0 for s in ran
            ),
            "prefilled_but_wrong_total": sum(
                s.get("prefilled_but_wrong_count") or 0 for s in ran
            ),
            "blank_field_total": sum(s.get("blank_field_count") or 0 for s in ran),
            "must_review_total": sum(s.get("must_review_count") or 0 for s in ran),
            "missing_total": sum(s.get("missing_count") or 0 for s in ran),
            "illegible_total": sum(s.get("illegible_token_count") or 0 for s in ran),
            "mean_elapsed_sec": (
                round(sum(elapsed) / len(elapsed), 2) if elapsed else None
            ),
            "repairable_ratio_overall": (
                round(rep_num / rep_den, 3) if rep_den else None
            ),
        },
        "per_sheet": pub_sheets,
    }


def compare_runs(base_run: dict[str, Any], other_run: dict[str, Any]) -> dict[str, Any]:
    """Comparação pareada por campo (§2.5) entre duas rodadas detalhadas.

    Pareia por document_id (interno) e publica por índice anônimo `sheet_N.campo`.
    Só campos comparados nas DUAS rodadas entram (interseção — justo com n pequeno).
    """
    a_meta, b_meta = base_run.get("meta", {}), other_run.get("meta", {})
    a_sheets = {s["document_id"]: s for s in base_run["per_sheet"] if s.get("ran")}
    b_sheets = {s["document_id"]: s for s in other_run["per_sheet"] if s.get("ran")}
    common = sorted(set(a_sheets) & set(b_sheets))

    fields: dict[str, str] = {}
    counts = {"both": 0, "only_baseline": 0, "only_vlm": 0, "neither": 0}
    a_chars = b_chars = 0
    a_succ = b_succ = 0
    for i, doc in enumerate(common, start=1):
        sa, sb = a_sheets[doc], b_sheets[doc]
        a_succ += 1 if sa.get("parse_table_success") else 0
        b_succ += 1 if sb.get("parse_table_success") else 0
        a_chars += sa.get("estimated_chars_to_type") or 0
        b_chars += sb.get("estimated_chars_to_type") or 0
        fa = sa.get("field_compare") or {}
        fb = sb.get("field_compare") or {}
        for fname in sorted(set(fa) & set(fb)):
            ca, cb = bool(fa[fname]["correct"]), bool(fb[fname]["correct"])
            outcome = (
                "both" if ca and cb else "only_baseline" if ca else "only_vlm" if cb else "neither"
            )
            counts[outcome] += 1
            fields[f"sheet_{i}.{fname}"] = outcome

    margin = counts["only_vlm"] - counts["only_baseline"]
    return {
        "baseline": {"reader": a_meta.get("reader"), "dpi": a_meta.get("dpi")},
        "vlm": {"reader": b_meta.get("reader"), "dpi": b_meta.get("dpi")},
        "n_sheets_paired": len(common),
        "n_fields_paired": sum(counts.values()),
        "counts": counts,
        "fields": fields,
        "parse_table_success_count": {"baseline": a_succ, "vlm": b_succ},
        "estimated_chars_to_type_total": {"baseline": a_chars, "vlm": b_chars},
        # G1 (EVAL_PROTOCOL §3): taxa agregada + margem pareada + esforço. O SLO de
        # tempo é decisão humana pendente — o gate nunca é dado como 'passou' aqui.
        "g1": {
            "rate_ok": b_succ >= a_succ,
            "paired_margin": margin,
            "margin_ok": margin >= 2,
            "chars_ok": b_chars < a_chars,
            "slo": "pending (EVAL_PROTOCOL §5)",
        },
    }


def render_summary(
    path: Path,
    run: dict[str, Any] | None = None,
    paired: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Merge no docs/eval_real_summary.json: 1 entrada por (reader, dpi) + `paired`.

    Retorna (texto_json, hits_de_pii). O chamador só escreve se hits == [] —
    segunda camada de defesa; a primeira é a whitelist por construção.
    """
    data: dict[str, Any] = {"protocol": "docs/EVAL_PROTOCOL.md", "runs": []}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data.update(existing)
                data.setdefault("runs", [])
        except json.JSONDecodeError:
            pass  # corrompido → recomeça; a fonte detalhada vive em private/audit/
    if run is not None:
        data["runs"] = [
            r
            for r in data["runs"]
            if not (r.get("reader") == run.get("reader") and r.get("dpi") == run.get("dpi"))
        ] + [run]
    if paired is not None:
        data["paired"] = paired
    text = json.dumps(data, indent=2, ensure_ascii=False)
    return text, scan_text_for_pii(text)


# --- relatório legado ANTES × DEPOIS (AUDITORIA_FOLHAS_REAIS.md) --------------


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
        "- **Iteração de OCR (Fase 4), medida:** baixar a rasterização para ~150 DPI recuperou a "
        "estrutura (eliminou `MISSED_INCIDENT`); já variar pré-processamento "
        "(grayscale/Otsu/autocontrast × PSM 3/4/6) **não deu ganho** no manuscrito cursivo — "
        "nem os dígitos da data foram lidos. O teto de fidelidade no custo-zero é o próprio "
        "Tesseract; subir exige um leitor melhor (VLM — sendo medido pelo modo instrumentado, "
        "ver docs/EVAL_PROTOCOL.md) ou fonte de melhor qualidade. O sistema degrada "
        "corretamente: tudo vai para revisão humana.",
        "- Números preliminares até a curadoria ser `verified_by_user` (plano R4).",
        "",
    ]
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------


def _legacy_compare(args: argparse.Namespace) -> int:
    """Modo legado: ANTES (escalar) × DEPOIS (tabela) → AUDITORIA_FOLHAS_REAIS.md."""
    curadoria = load_curadoria()
    if not curadoria:
        print("Nenhuma curadoria válida em private/curadoria/ — nada a auditar.", file=sys.stderr)
        return 1

    antes_per, antes_agg = run_config(curadoria, CONFIG_PATH)
    depois_per, depois_agg = run_config(curadoria, TABLE_CONFIG_PATH)

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


def _write_summary(
    run: dict[str, Any] | None = None, paired: dict[str, Any] | None = None
) -> int:
    text, pii = render_summary(SUMMARY_PATH, run=run, paired=paired)
    if pii:
        print("ABORTADO: PII detectada no resumo público:", file=sys.stderr)
        for h in pii:
            print(h, file=sys.stderr)
        return 2
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(text, encoding="utf-8")
    print(f"Escrito {SUMMARY_PATH}", file=sys.stderr)
    return 0


def _instrumented(args: argparse.Namespace) -> int:
    """Modo instrumentado (default): 1 rodada = (leitor, dpi) sobre a config de tabela."""
    curadoria = load_curadoria()
    if not curadoria:
        print("Nenhuma curadoria válida em private/curadoria/ — nada a auditar.", file=sys.stderr)
        return 1
    if args.n:
        curadoria = curadoria[: args.n]

    config = load_config(TABLE_CONFIG_PATH)
    vision = get_vision_client(args.vision)
    meta = run_metadata(args.vision, args.dpi)
    per_sheet = [run_sheet(cur, config, vision=vision, dpi=args.dpi) for cur in curadoria]

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    detailed_path = AUDIT_DIR / f"eval_real_detailed_{args.vision}_dpi{args.dpi}.json"
    detailed_path.write_text(
        json.dumps({"meta": meta, "per_sheet": per_sheet}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Escrito {detailed_path}", file=sys.stderr)

    public = build_public_run(meta, per_sheet)
    if not args.no_report:
        code = _write_summary(run=public)
        if code:
            return code
    print(json.dumps(public, indent=2, ensure_ascii=False))
    return 0


def _compare(args: argparse.Namespace) -> int:
    base_path, other_path = (Path(p) for p in args.compare)
    paired = compare_runs(
        json.loads(base_path.read_text(encoding="utf-8")),
        json.loads(other_path.read_text(encoding="utf-8")),
    )
    if not args.no_report:
        code = _write_summary(paired=paired)
        if code:
            return code
    print(json.dumps(paired, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Medição em folhas reais (EVAL_PROTOCOL): instrumentado, pareado ou legado."
    )
    parser.add_argument(
        "--vision",
        choices=["local_ocr", "paddle_ocr", "local_vlm", "mock"],
        default="local_ocr",
        help="leitor da rodada instrumentada (resolvido via factory)",
    )
    parser.add_argument("--dpi", type=int, default=OCR_DPI, help="DPI da rasterização")
    parser.add_argument("--n", type=int, default=0, help="máx. de folhas (0 = todas)")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE_JSON", "VLM_JSON"),
        help="compara duas rodadas detalhadas (pareado por campo, gate G1)",
    )
    parser.add_argument(
        "--legacy-compare",
        action="store_true",
        help="modo legado ANTES×DEPOIS -> docs/AUDITORIA_FOLHAS_REAIS.md",
    )
    parser.add_argument("--no-report", action="store_true", help="não escrever docs públicos")
    args = parser.parse_args(argv)

    if args.dpi <= 0:
        parser.error("--dpi deve ser um inteiro positivo")
    if args.n < 0:
        parser.error("--n não pode ser negativo")

    if args.compare:
        return _compare(args)
    if args.legacy_compare:
        return _legacy_compare(args)
    return _instrumented(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
