"""Tests for the normalize stage (src/pipeline/normalize.py)."""

from __future__ import annotations

from src.pipeline.normalize import normalize
from src.schema.extraction import AuditedField, RawDocumentExtraction, RawHeader, RawRow


def _af(value: object, status: str = "accepted") -> AuditedField:
    return AuditedField(value=value, status=status, confidence=1.0)  # type: ignore[arg-type]


def _raw(rows: list[RawRow], header: RawHeader | None = None) -> RawDocumentExtraction:
    return RawDocumentExtraction(
        report_type="controle_ocorrencias",
        header=header or RawHeader(),
        rows=rows,
    )


def test_sem_alteracao_rows_make_no_occurrence() -> None:
    raw = _raw([RawRow(sem_alteracao=True), RawRow(sem_alteracao=True)])
    m = normalize(raw)
    assert m.no_occurrence is True
    assert m.occurrences == []


def test_empty_rows_make_no_occurrence() -> None:
    raw = _raw([RawRow(), RawRow()])
    m = normalize(raw)
    assert m.no_occurrence is True


def test_single_occurrence_built() -> None:
    raw = _raw(
        [RawRow(item=_af("Crachá"), descricao=_af("Feito crachá."), resolvido=_af("sim"))]
    )
    m = normalize(raw)
    assert m.no_occurrence is False
    assert len(m.occurrences) == 1
    occ = m.occurrences[0]
    assert occ.category == "Crachá"
    assert occ.resolved is True


def test_double_time_entry_exit() -> None:
    raw = _raw([RawRow(item=_af("Acesso"), hora=_af("17:19 saída 17:52"))])
    occ = normalize(raw).occurrences[0]
    assert occ.entry_time == "17:19"
    assert occ.exit_time == "17:52"


def test_single_time_entry_only() -> None:
    raw = _raw([RawRow(item=_af("Crachá"), hora=_af("13:00"))])
    occ = normalize(raw).occurrences[0]
    assert occ.entry_time == "13:00"
    assert occ.exit_time is None


def test_resolved_negative() -> None:
    raw = _raw([RawRow(item=_af("Alarme"), resolvido=_af("não"))])
    assert normalize(raw).occurrences[0].resolved is False


def test_needs_review_when_cell_must_review() -> None:
    raw = _raw([RawRow(item=_af("Acesso", status="must_review"))])
    assert normalize(raw).occurrences[0].needs_review is True


def test_guards_split_from_string() -> None:
    header = RawHeader(vigilantes=_af("Ana, Bruno e Carlos"))
    m = normalize(_raw([], header=header))
    assert m.shift.guards == ["Ana", "Bruno", "Carlos"]


def test_guards_from_list_value() -> None:
    header = RawHeader(vigilantes=_af(["Ana", "Bruno"]))
    m = normalize(_raw([], header=header))
    assert m.shift.guards == ["Ana", "Bruno"]


def test_header_unit_and_date() -> None:
    header = RawHeader(data_turno=_af("23/06"), unidade=_af("Posto"))
    m = normalize(_raw([], header=header))
    assert m.shift.date == "23/06"
    assert m.shift.unit == "Posto"


def test_mixed_rows_only_real_occurrence_kept() -> None:
    raw = _raw(
        [
            RawRow(item=_af("Acesso"), descricao=_af("Entrada de prestador.")),
            RawRow(sem_alteracao=True),
            RawRow(),
        ]
    )
    m = normalize(raw)
    assert len(m.occurrences) == 1
    assert m.no_occurrence is False
