"""RuleBasedTableExtractor — OCR de folha de tabela → `RawDocumentExtraction` (ADR R1/R2).

Determinístico, zero-custo (sem modelo). Estratégia honesta dado o limite do OCR cursivo:
- **Cabeçalho** ancorado nos rótulos impressos (`ocr_aliases`) — que o Tesseract lê bem.
- **Tabela** delimitada entre a linha de cabeçalho de coluna ("Item ... Descrição ...") e o rodapé
  ("Ronda"). Linhas `S/A` textuais → `sem_alteracao` (mata FALSE_INCIDENT). Linhas com conteúdo
  viram linha com `descricao` e **status must_review** (humano confirma/corrige — estilo ExpenseIt).

Design (plano "nunca adivinhar"): todo valor lido entra com confiança < limiar → `must_review`;
nada é dado como certo. A segmentação fina de colunas a partir de OCR cursivo é inviável — o ganho
aqui é **estrutura correta + S/A tratado + trilha de auditoria + revisão humana**, não HTR perfeito.
"""

from __future__ import annotations

import re

from src.schema.config import ReportConfig
from src.schema.extraction import (
    AuditedField,
    RawDocumentExtraction,
    RawHeader,
    RawRow,
)

# Conservative heuristic placeholders, not calibrated probabilities. They distinguish
# rule-prefilled values from missing=0.0 and remain deliberately below the 0.70 critic
# threshold. Review routing is also enforced by status="must_review".
HEADER_REVIEW_PLACEHOLDER_CONFIDENCE = 0.65
ROW_REVIEW_PLACEHOLDER_CONFIDENCE = 0.40

_TIME = re.compile(r"\d{1,2}:\d{2}")
# S/A e variações de OCR (barra lida como I/1/l/|, S como 5, etc.).
_SA = re.compile(r"^[S5]\s*[/|1lI]\s*A$", re.IGNORECASE)
# Linha de cabeçalho da tabela e marcador de rodapé (texto impresso, OCR confiável).
_COLHDR = re.compile(r"^\s*[iIlL]tem\b.*\bhora\b.*(?:descri|ocorr)", re.IGNORECASE)
_FOOTER = re.compile(r"^\s*ronda(?:\s*[:\-]?\s*(?:x|ok))?\s*$", re.IGNORECASE)


def _is_sa(text: str) -> bool:
    return bool(_SA.match(text.strip()))


def _found(value: str, evidence: str, confidence: float, page: int | None = None) -> AuditedField:
    return AuditedField(
        value=value,
        confidence=confidence,
        source="rule",
        status="must_review",
        evidence=evidence,
        page=page,
    )


class RuleBasedTableExtractor:
    """Extrai `RawDocumentExtraction` da transcrição OCR, guiado pela config."""

    def __init__(self, config: ReportConfig) -> None:
        self._report_type = config.report_type
        self._header_fields = {f.name: f for f in config.fields if f.type != "table"}
        self._has_table = any(f.type == "table" for f in config.fields)

    def _find_after_label(
        self, pages: list[list[str]], aliases: list[str]
    ) -> tuple[str, str, int] | None:
        """Retorna (valor, linha-evidência, página) após o rótulo, ou None."""
        for alias in aliases:
            needle = alias.rstrip(":").lower()
            for page, lines in enumerate(pages):
                for line in lines:
                    idx = line.lower().find(needle)
                    if idx >= 0:
                        value = line[idx + len(needle) :].lstrip(" :\t").strip()
                        if value:
                            return value, line.strip(), page
        return None

    def _extract_header(self, pages: list[list[str]]) -> RawHeader:
        cells: dict[str, AuditedField] = {}
        for name, field in self._header_fields.items():
            aliases = field.ocr_aliases or [name]
            hit = self._find_after_label(pages, aliases)
            cells[name] = (
                _found(hit[0], hit[1], HEADER_REVIEW_PLACEHOLDER_CONFIDENCE, page=hit[2])
                if hit
                else AuditedField()
            )
        return RawHeader(
            data_turno=cells.get("data_turno", AuditedField()),
            vigilantes=cells.get("vigilantes", AuditedField()),
            unidade=cells.get("unidade", AuditedField()),
        )

    def _table_region(self, lines: list[str]) -> list[str] | None:
        start = next((i for i, ln in enumerate(lines) if _COLHDR.search(ln)), None)
        if start is None:
            return None
        end = next(
            (i for i in range(start + 1, len(lines)) if _FOOTER.search(lines[i])), len(lines)
        )
        return lines[start + 1 : end]

    def _content_row(self, buffer: list[str], page: int) -> RawRow:
        joined = " ".join(buffer).strip()
        times = _TIME.findall(joined)
        hora = (
            _found(" ".join(times), joined, ROW_REVIEW_PLACEHOLDER_CONFIDENCE, page=page)
            if times
            else AuditedField()
        )
        return RawRow(
            descricao=_found(joined, joined, ROW_REVIEW_PLACEHOLDER_CONFIDENCE, page=page),
            hora=hora,
        )

    def _extract_rows(self, region: list[str], page: int = 0) -> list[RawRow]:
        rows: list[RawRow] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                rows.append(self._content_row(buffer, page))
                buffer.clear()

        for line in region:
            text = line.strip()
            if not text:
                flush()
            elif _is_sa(text):
                flush()
                rows.append(RawRow(sem_alteracao=True))
            else:
                buffer.append(text)
        flush()
        return rows

    def extract(self, transcription: str) -> RawDocumentExtraction:
        pages = [page.splitlines() for page in transcription.split("\f")]
        if self._has_table:
            regions = [self._table_region(lines) for lines in pages]
            table_found = all(region is not None for region in regions)
            rows = [
                row
                for page, region in enumerate(regions)
                if region is not None
                for row in self._extract_rows(region, page=page)
            ]
        else:
            table_found = True
            rows = []
        return RawDocumentExtraction(
            report_type=self._report_type,
            header=self._extract_header(pages),
            tabela_encontrada=table_found,
            rows=rows,
        )
