"""OCR Quality Gate — decide se a transcrição sustenta processamento automático.

A validação manual em folhas reais manuscritas mostrou OCR ilegível. O produto correto
não pode deixar esse ruído virar dado confiável. Este gate classifica a qualidade do OCR
e, quando insuficiente, faz o pipeline entrar em modo seguro (sem classificação automática,
sem rascunho operacional) — conduzindo à transcrição/revisão manual.

Status:
- `good`   — estrutura + conteúdo legível suficiente para seguir.
- `low`    — legível parcialmente; segue, mas tudo continua em revisão humana.
- `failed` — vazio/curto, ou ocorrência com conteúdo ilegível -> requer transcrição manual.

Honesto e determinístico (sem modelo). Calibrado nas folhas reais: o sinal mais robusto é a
densidade de "palavras de conteúdo" FORA dos rótulos impressos (o OCR lê os rótulos da folha,
mas devolve ruído no manuscrito). Uma folha S/A legítima tem pouco conteúdo — por isso só
exigimos conteúdo quando há ocorrência declarada.
"""

from __future__ import annotations

import re

from src.schema.config import ReportConfig
from src.schema.state import PipelineState

OCR_GOOD = "good"
OCR_LOW = "low"
OCR_FAILED = "failed"

_MIN_CHARS = 30
_MIN_CONTENT_WORDS = 4  # com ocorrência, abaixo disso o conteúdo está ilegível
_GOOD_CONTENT_WORDS = 8
_WORD = re.compile(r"[a-zA-ZáéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]{3,}")

# Termos impressos do formulário (chrome) que não contam como "conteúdo".
_FORM_CHROME = (
    "controle de ocorrencias controle de ocorrências ronda monitoramento cameras câmeras "
    "acesso pessoas cargas revista veiculos veículos outros sim nao não item hora descricao "
    "descrição ocorrencia ocorrência acao ação resolvido data turno vigilantes vigilante unidade"
)


def _label_words(config: ReportConfig) -> set[str]:
    """Palavras dos rótulos impressos (aliases da config + chrome do formulário)."""
    words: set[str] = set(_WORD.findall(_FORM_CHROME.lower()))
    for field in config.fields:
        for alias in field.ocr_aliases or []:
            words.update(_WORD.findall(alias.lower()))
        for col in field.columns or []:
            for alias in col.ocr_aliases or []:
                words.update(_WORD.findall(alias.lower()))
    return words


def assess_ocr_quality(state: PipelineState, config: ReportConfig) -> tuple[str, str]:
    """Avalia a qualidade do OCR; retorna (status, motivo). Não muta o estado."""
    text = state.transcription or ""
    if len(text.strip()) < _MIN_CHARS:
        return OCR_FAILED, "Transcrição vazia ou muito curta para o tipo de documento."

    labels = _label_words(config)
    content = [w for w in _WORD.findall(text.lower()) if w not in labels]
    n = len(content)

    confirmed_no_occurrence = bool(
        state.normalized and state.normalized.disposition == "none"
    )
    if not confirmed_no_occurrence and n < _MIN_CONTENT_WORDS:
        return (
            OCR_FAILED,
            "Conteúdo manuscrito ilegível para o OCR — requer transcrição manual.",
        )
    if n < _GOOD_CONTENT_WORDS:
        return OCR_LOW, "OCR de baixa qualidade — confira/complete os campos antes de seguir."
    return OCR_GOOD, "Qualidade de OCR aceitável (confirmação humana ainda obrigatória)."
