# STATUS — Fábrica de dataset sintético `tier_c` (branch `SSI-1002-hardening`)

> **Propósito deste arquivo:** registro de retomada entre sessões (context file).
> Diz em que ponto o plano da fábrica está, o que foi feito (com commit) e o que falta.
> **Atualize-o ao final de cada micro-passo/sessão.** O contrato normativo é
> [`DATASET_CONTRACT.md`](DATASET_CONTRACT.md); o plano aprovado (PRs D0–D6) está
> resumido nele e no [`ROADMAP.md`](ROADMAP.md). Legado da régua real:
> [`STATUS_PR1.md`](STATUS_PR1.md).

## O que a fábrica entrega

Folhas "Controle de ocorrências" 100% fictícias, reproduzíveis por seed: PDF + gabarito
JSON (formato curadoria + bloco `synthetic`) + manifests train/val/test + eval sintético
com **as mesmas fórmulas** do `EVAL_PROTOCOL.md` §2. Régua oficial: gates **G-S0…G-S3 e
G1-S** (`DATASET_CONTRACT.md` §10) — decisão de leitor **sem folha real**.

## Escada de PRs (plano aprovado)

| PR | Entrega | Status |
|---|---|---|
| **D0** | Contrato normativo + amendas nos 5 docs (régua reposicionada) | ✅ (commits abaixo) |
| **D1** | 5 fontes handwriting OFL + `FONTS.md` (registro source/license/sha256) + `tests/test_fonts_coverage.py` (cobertura ã/ç/õ…) + `assets/fonts/README.md` (política de binários) | ✅ (commits abaixo) |
| **D2** | `data/generators/occurrences.py` (vocabulários ~18 tipos + `SheetRecord` no vocabulário da curadoria + perfis balanced/operational) + extensão de `priors.py` + `messiness_table` + held-out 20% vocab/frases | ⬜ |
| **D3** | `data/generators/templates/controle_ocorrencias.py` — render tabela 5 colunas (8–10 linhas), variantes A/B (+C só test), retorno `(Image, ideal_lines)`, teste de contrato pré-G-S0 | ⬜ (D4 pode andar em paralelo) |
| **D4** | `degrade_photo` (perspectiva/sombra/corte ≤3%/downscale) + knob `clean\|scan\|photo` + bandas held-out 80/20 por split | ⬜ |
| **D5** | `tier_c.py::build_tier_c` + `CANONICAL_DATASETS` + `scripts/gen_sheets.py` + Make `gen-sheets DATASET=...` + manifesto congelado (sha256 de PNG+gt canônico, nunca PDF) + estender `_ALLOWED_SAMPLE_NAMES` p/ `sample_tc-\d+` | ⬜ |
| **D6** | `evals/eval_extraction_synthetic.py` (reusa `load_curadoria(directory, valid_status)`/`run_sheet`) + `--split val` default + `reader_metrics` × `parser_ceiling` + `docs/eval_synthetic_summary.json` + Make `eval-synthetic` | ⬜ |

## Feito (com commit)

| Item | Commit |
|---|---|
| `docs/DATASET_CONTRACT.md` — contrato normativo completo (schema, datasets canônicos, held-out 4D, gates G-S0…G-S3 + G1-S com protocolo de calibração val→congela→test, hash policy, datasets públicos, escala honesta) | `a5ebfea` |
| `EVAL_PROTOCOL.md` — G1–G3 reais → **legado/opcional**; fórmulas §2 seguem normativas (reusadas pelo eval sintético) | `ff84b1c` |
| `ROADMAP.md` — escada de PRs aponta G-S/G1-S como decisão | `ebf2cf2` |
| `STATUS_PR1.md` — nota de legado na evidência G1 real (arquivada, não apagada) | `c6e65fe` |
| `CURADORIA_FORMATO.md` — enum `synthetic_ground_truth` + campo `truth_source` formalizados | `246dd17` |
| `README.md` — régua de leitor aponta para o contrato sintético | `46da9dd` |
| Este arquivo de status | `d88a5a0` |
| **PR-D1** Caveat / Shadows Into Light / Just Me Again Down Here / Patrick Hand / Reenie Beanie (.ttf + OFL.txt cada) — glifos PT-BR verificados por código + inspeção visual ANTES do commit | `012fc96` `51a13f5` `60fd81a` `11b397e` `7a8b9b7` |
| `assets/fonts/FONTS.md` — registro upstream/atribuição/sha256 por fonte | `a1889db` |
| `tests/test_fonts_coverage.py` — bundle presente + acentos (bitmap ≠ .notdef) + OFL.txt ao lado de cada .ttf (11 testes) | `5ff62fc` |
| `assets/fonts/README.md` — política no-binary → OFL bundladas (deliberado) | commit desta entrega |

Evidência PR-D1: `make check` → **506 passed, 1 skipped**; `make privacy-check` OK.
Nota: *Homemade Apple* descartada (Apache 2.0, não OFL); *Reenie Beanie* no lugar.

## Decisões congeladas (não rediscutir sem novo registro)

- Gabarito = formato curadoria + bloco `synthetic`; `review_status: synthetic_ground_truth`
  + `truth_source: generator` (nunca `verified_by_user` em folha gerada).
- `cabecalho.data` = **string exata desenhada** no campo "Data e Turno" (senão OCR_MISS falso).
- 1 família de template (controle de ocorrências), plugável; ~18 tipos como conteúdo de linha.
- Perfis `balanced` (default) e `operational`; held-out em 4 dimensões (§5 do contrato).
- Hash: PNG + gt canônico, nunca PDF; validade sob `uv.lock`; drift ⇒ bump `tier_c/vN`.
- Eval sintético roda em `val` por default; `test` é ato explícito (anti-tuning).
- `reader_metrics` (entra no G1-S) separado de `parser_ceiling` (item/acao/resolvido
  saem `missing` por construção do extractor line-based).
- VLM só em subamostra seedada a DPI 100 (~177 s/folha medido; 150 estoura VRAM).

## Regras de trabalho desta trilha (pedido do usuário)

- **Micro-commits em cada mudança mínima** (autor `JoaoMiltzarek <joaogabrielzek@gmail.com>`,
  formato `tipo(SSI-1002): descrição`); **nunca push** (o usuário pusha).
- **Atualizar este arquivo ao final de cada sessão/micro-passo** — ele é o context de retomada.
- `make check` verde antes de avançar de PR; `make privacy-check` após qualquer doc/artefato público.

## Como retomar numa sessão nova

```bash
git log --oneline -20          # commits da tabela acima
make check                     # deve estar verde antes de qualquer mudança (506+ testes)
# Próximo passo: PR-D2 (gerador de gabarito) — ver escada acima e DATASET_CONTRACT.md §2/§5-§7.
# D2 exige: data/generators/occurrences.py (SheetRecord no vocabulário da curadoria +
# ~18 tipos de item com bancos descrição/ação, listas fixas revisadas), extensão de
# priors.py (P_N_OCORRENCIAS, P_SA por perfil balanced/operational, P_RISCADO_VS_SA,
# nº vigilantes 1-3), messiness_table (ops de messiness.py por célula + legibility),
# held-out 20% (nomes/unidades/frases só no test, seed própria em meta), e testes:
# determinismo, distribuição por perfil, held-out disjunto, serialização == formato
# curadoria + review_status synthetic_ground_truth (invariante: cabecalho.data = string
# desenhada "DD/MM/AAAA - Turno", nunca só a data).
```
