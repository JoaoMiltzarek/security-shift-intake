# AUDITORIA — Folhas reais (baseline do sistema atual)

> Gerado por `evals/eval_extraction_real.py`. **Nenhum número é digitado à mão.** Contém apenas métricas agregadas + exemplos sintéticos — dados reais ficam em `private/` (plano R6/regra #2). Detalhe com PII em `private/audit/metrics_real.json`.

> ⚠️ **PRELIMINAR.** Nenhuma curadoria está `verified_by_user` ainda (0/4). Os números abaixo usam a transcrição automática como ground-truth e **devem ser reconferidos** (plano R4).

## Cobertura

- Folhas com curadoria: **4**
- Rodadas no pipeline: **2**
- Pendentes (arquivo da imagem ausente em `private/reais/`): **2**
- Confiança média do OCR (Tesseract): **0.694**

## Captura de ocorrências (o dado mais importante)

- Ocorrências reais na curadoria: **1**
- Capturadas com fidelidade pelo sistema atual: **0**

## Status dos campos (plano R2)

| status | contagem |
|---|---|
| accepted | 0 |
| must_review | 4 |
| missing | 8 |

## Erros por severidade (plano R3)

| severidade | contagem |
|---|---|
| BLOCKER | 2 |
| HIGH | 0 |
| MEDIUM | 6 |
| LOW (revisão humana, desejado) | 12 |

## Erros por tipo

| tipo | severidade | contagem |
|---|---|---|
| FALSE_INCIDENT | BLOCKER | 1 |
| MISSED_INCIDENT | BLOCKER | 1 |
| BAD_NORMALIZATION | HIGH | 0 |
| TABLE_ROW_SPLIT_ERROR | HIGH | 0 |
| FIELD_NOT_FOUND | MEDIUM | 6 |
| OCR_MISS | MEDIUM | 0 |
| NEEDS_HUMAN_REVIEW | LOW | 12 |

## Leitura honesta

- O Tesseract lê **rótulos impressos** bem, mas **valores cursivos** viram ruído — esperado para OCR livre em manuscrito (não é um defeito do pipeline).
- O achado estrutural: a config atual modela **incidente único escalar**; a folha real é uma **tabela de N linhas** (Item/Hora/Descrição/Ação/Resolvido) com cabeçalho de vários vigilantes. O conteúdo das ocorrências **não tem onde ser representado** hoje → `MISSED_INCIDENT`/`TABLE_ROW_SPLIT_ERROR`. Isso motiva o ADR.
- `BLOCKER`/`HIGH` são a prioridade da reforma; `LOW` (must_review) é o comportamento desejado ("nunca adivinhar").
