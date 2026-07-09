# AUDITORIA — Folhas reais (ANTES escalar × DEPOIS tabela)

> Gerado por `evals/eval_extraction_real.py`. **Nenhum número é digitado à mão.** Só métricas agregadas — dados reais ficam em `private/` (plano R6/regra #2). Detalhe com PII em `private/audit/metrics_real.json`.

- **ANTES** = config escalar `htmicron_security` (incidente único).
- **DEPOIS** = config `controle_ocorrencias` (cabeçalho + tabela de N linhas).

## Cobertura (igual nos dois)

- Folhas com curadoria: **4** | rodadas: **2** | pendentes: **2**

## Ocorrências (o dado mais importante)

| métrica | ANTES | DEPOIS |
|---|---|---|
| ocorrências reais (curadoria) | 1 | 1 |
| **representadas** (têm onde existir) | 0 | 1 |
| capturadas fielmente (CER ≤ 0.5) | 0 | 0 |

## Erros por severidade (plano R3)

| severidade | ANTES | DEPOIS |
|---|---|---|
| BLOCKER | 2 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 6 | 6 |
| LOW (revisão humana, desejado) | 12 | 8 |

## Status dos campos (plano R2)

| status | ANTES | DEPOIS |
|---|---|---|
| accepted | 0 | 1 |
| must_review | 6 | 5 |
| missing | 6 | 3 |

## Erros por tipo (DEPOIS)

| tipo | severidade | DEPOIS |
|---|---|---|
| FALSE_INCIDENT | BLOCKER | 0 |
| MISSED_INCIDENT | BLOCKER | 0 |
| BAD_NORMALIZATION | HIGH | 0 |
| TABLE_ROW_SPLIT_ERROR | HIGH | 0 |
| FIELD_NOT_FOUND | MEDIUM | 3 |
| OCR_MISS | MEDIUM | 3 |
| NEEDS_HUMAN_REVIEW | LOW | 8 |

## Leitura honesta

- A reforma (caminho tabela) faz a ocorrência **ser representada** e trata `S/A` como sem alteração — eliminando os `BLOCKER` (`FALSE_INCIDENT` na folha S/A e `MISSED_INCIDENT` por não ter onde guardar a ocorrência).
- O OCR cursivo do Tesseract continua fraco: o conteúdo capturado entra como `must_review` (LOW, desejado) para o humano confirmar/corrigir — não some nem é dado como certo. Fidelidade de texto (CER) só melhora com OCR/manuscrito melhor.
- **Iteração de OCR (Fase 4), medida:** baixar a rasterização para ~150 DPI recuperou a estrutura (eliminou `MISSED_INCIDENT`); já variar pré-processamento (grayscale/Otsu/autocontrast × PSM 3/4/6) **não deu ganho** no manuscrito cursivo — nem os dígitos da data foram lidos. O teto de fidelidade no custo-zero é o próprio Tesseract; subir exige um leitor melhor (VLM — sendo medido pelo modo instrumentado, ver docs/EVAL_PROTOCOL.md) ou fonte de melhor qualidade. O sistema degrada corretamente: tudo vai para revisão humana.
- Números preliminares até a curadoria ser `verified_by_user` (plano R4).
