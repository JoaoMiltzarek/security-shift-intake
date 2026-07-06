"""Contrato VLM→tabela CONGELADO (PR-1): a transcrição que o prompt do VLM promete
(src/clients/local_vlm.py:_TRANSCRIPTION_PROMPT — rótulos impressos preservados,
quebras de linha preservadas, S/A preservado, `[ilegível]` por token ilegível)
atravessa extract_table → validate_table → assess_ocr_quality sem quebrar.

Se o qwen real violar este formato (medido na rodada local), a correção é no
prompt ou nestas fixtures — NUNCA no orquestrador. Congelar o contrato antes de
qualquer escalonamento é o que impede a PR-2 de nascer sobre areia
(docs/EVAL_PROTOCOL.md §8).

NOTA (fixtures): amostras sintéticas no formato prometido. Após a primeira rodada
local, capturar transcrições reais do qwen sobre a folha SINTÉTICA de `samples/`
(sem PII) e substituir/complementar estas fixtures.
"""

from __future__ import annotations

from pathlib import Path

from src.pipeline.extract_table import extract_table
from src.pipeline.ocr_quality import OCR_FAILED, assess_ocr_quality
from src.pipeline.validate import validate_table
from src.schema.loader import load_config
from src.schema.state import PipelineState

CFG = load_config(Path("configs/controle_ocorrencias.yaml"))

# Folha S/A no formato do contrato (rótulos + quebras + S/A preservados).
_VLM_SA = """CONTROLE DE OCORRÊNCIAS
Data e Turno: 23/06 noturno
Vigilantes: Ana
Unidade: Portaria
Item Hora Descrição da Ocorrência Ação Resolvido (sim/não)
S/A
Ronda: ok
"""

# Folha com 1 ocorrência real.
_VLM_OCC = """CONTROLE DE OCORRÊNCIAS
Data e Turno: 23/06 noturno
Vigilantes: Ana
Unidade: Portaria
Item Hora Descrição da Ocorrência Ação Resolvido (sim/não)
Crachá 13:40 Prestador acessou a sala de TI Acompanhado sim
Ronda: ok
"""

# Token ilegível marcado como o prompt manda — nunca adivinhado.
_VLM_ILEGIVEL = """CONTROLE DE OCORRÊNCIAS
Data e Turno: 23/06 noturno
Vigilantes: Ana
Unidade: Portaria
Item Hora Descrição da Ocorrência Ação Resolvido (sim/não)
Crachá 13:40 Prestador [ilegível] no portão 3 Acompanhado sim
Ronda: ok
"""

# Rótulos com variação de caixa (o VLM pode normalizar maiúsculas/minúsculas).
_VLM_CASE = """controle de ocorrências
DATA E TURNO: 23/06 noturno
vigilantes: Ana
UNIDADE: Portaria
Item Hora Descrição da Ocorrência Ação Resolvido (sim/não)
S/A
Ronda: ok
"""

# FORA do contrato: markdown com tabela de pipes e negrito (failure matrix §8).
_VLM_MARKDOWN = """## Transcrição da folha

| Campo | Valor |
|---|---|
| **Data e Turno** | 23/06 noturno |
| **Vigilantes** | Ana |

O documento registra **acesso de prestador** para manutenção preventiva,
acompanhado pela equipe durante todo o período noturno.
"""


def _run(text: str) -> PipelineState:
    state = PipelineState(source_pdf=Path("fixture.png"), transcription=text)
    state = extract_table(state, CFG)
    return validate_table(state, CFG)


# --- folha S/A ----------------------------------------------------------------


def test_vlm_contract_sa_sheet_yields_no_occurrence() -> None:
    state = _run(_VLM_SA)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is True
    sa = next(f for f in state.extracted_fields if f.name == "ocorrencias")
    assert sa.value == "(sem alteração)"
    assert sa.must_review is False


def test_vlm_contract_sa_sheet_not_ocr_failed() -> None:
    state = _run(_VLM_SA)
    status, _ = assess_ocr_quality(state, CFG)
    assert status != OCR_FAILED


# --- folha com 1 ocorrência -----------------------------------------------------


def test_vlm_contract_occurrence_represented() -> None:
    state = _run(_VLM_OCC)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert len(state.normalized.occurrences) == 1
    desc = state.normalized.occurrences[0].description or ""
    assert "Prestador acessou a sala de TI" in desc


def test_vlm_contract_occurrence_routed_to_human() -> None:
    # Valor lido entra com confiança < limiar → must_review (nunca dado como certo).
    state = _run(_VLM_OCC)
    assert "ocorrencia_1" in state.must_review_fields


def test_vlm_contract_header_captured_but_must_review() -> None:
    state = _run(_VLM_OCC)
    header = {f.name: f for f in state.extracted_fields}
    assert header["data_turno"].value == "23/06 noturno"
    assert header["unidade"].value == "Portaria"
    assert header["data_turno"].must_review is True  # design: 0.65 < 0.70


# --- [ilegível] -----------------------------------------------------------------


def test_vlm_contract_illegible_token_preserved_verbatim() -> None:
    state = _run(_VLM_ILEGIVEL)
    assert state.normalized is not None
    desc = state.normalized.occurrences[0].description or ""
    assert "[ilegível]" in desc  # preservado, nunca "corrigido" ou adivinhado
    assert (state.transcription or "").count("[ilegível]") == 1


# --- variação de caixa nos rótulos ----------------------------------------------


def test_vlm_contract_labels_case_insensitive() -> None:
    state = _run(_VLM_CASE)
    header = {f.name: f for f in state.extracted_fields}
    assert header["data_turno"].value == "23/06 noturno"
    assert header["unidade"].value == "Portaria"
    assert state.normalized is not None
    assert state.normalized.no_occurrence is True


# --- fora do contrato: markdown (failure matrix) ---------------------------------


def test_vlm_contract_markdown_degrades_to_review() -> None:
    state = _run(_VLM_MARKDOWN)
    assert state.normalized is not None
    # Nunca inventa ocorrência aceita a partir de prosa/markdown.
    assert state.normalized.occurrences == []
    for f in state.extracted_fields:
        if f.name.startswith("ocorrencia_"):
            assert f.must_review or f.status != "accepted"
    # O gate humano segura: há pendência obrigatória (folha nunca sai limpa).
    assert state.must_review_fields
