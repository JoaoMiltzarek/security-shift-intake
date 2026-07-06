# STATUS — Fábrica de dataset sintético `tier_c` (branch `SSI-1002-tier-c-eval`)

> **Nota de branch (2026-07-05):** D0–D5 nasceram em `SSI-1002-hardening`, que foi
> mergeada em `main` via PRs #9/#10 (+ merge do cockpit de evidência). A D6 foi
> concluída em `SSI-1002-tier-c-eval`, criada a partir desse `main` consolidado.

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
| **D2** | `data/generators/occurrences.py` (vocabulários ~18 tipos + `SheetRecord` no vocabulário da curadoria + perfis balanced/operational) + extensão de `priors.py` + `messiness_table` + held-out 20% vocab/frases | ✅ (commits abaixo) |
| **D3** | `data/generators/templates/controle_ocorrencias.py` — render tabela 5 colunas (9 linhas), variantes A/B (+C só test), `RenderResult(image, ideal_lines, font_name)`, teste de contrato pré-G-S0 | ✅ (commits abaixo) |
| **D4** | `degrade_photo` (perspectiva/sombra/corte ≤3%/downscale) + bandas held-out 80/20 por split (`Band`, `_banded`; knob `clean\|scan\|photo` materializa na D5) | ✅ (commits abaixo) |
| **D5** | `tier_c.py::build_tier_c` + `CANONICAL_DATASETS` + `scripts/gen_sheets.py` + Make `gen-sheets DATASET=...` + manifesto congelado (sha256 de PNG+gt canônico, nunca PDF) + guard `sample_tc-\d+` | ✅ (commits abaixo) |
| **D6** | `evals/eval_extraction_synthetic.py` (reusa `load_curadoria(directory, valid_status)`/`run_sheet`) + `--split val` default + `reader_metrics` × `parser_ceiling` + `docs/eval_synthetic_summary.json` + Make `eval-synthetic` | ✅ (commits abaixo) |

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

| **PR-D2** priors tier_c (S/A por perfil, n ocorrências/vigilantes, riscado, hora dupla, resolvido, UNIDADES) | `0db6aa9` |
| `occurrences.py` — SheetRecord/vocab/generate_sheet/vocab_for_split/to_curadoria_dict | `0df4ee6` |
| `test_occurrences.py` — 11 testes incl. `test_heldout_vocab_disjoint`/`test_heldout_templates_disjoint` (G-S3) | `6280b71` |
| `messiness_table.py` — SheetSurface por célula (ops reusadas de messiness.py, legibility, P_ILLEGIBLE=0.05) | `ac99950` |
| `test_messiness_table.py` — 6 testes (data intacta §2.2, join vigilantes §11.2, hora dupla §11.4, ops/illegible) | `3dde19e` |

Evidência PR-D2: `make check` → **523 passed, 1 skipped**; `make privacy-check` OK.
Nota de design D2: o campo de data NÃO recebe messiness (mantém o invariante §2.2
`cabecalho.data == string desenhada` sem exceções); `vocab_for_split` usa seed própria
(`DEFAULT_HELDOUT_SEED=7`, fração 0.20) — registrar no meta.json na PR-D5.

| **PR-D3** fix: banco purgado da palavra do rodapé (`_FOOTER` truncaria a tabela; "Ronda"→"Inspeção" etc.) + `test_bank_never_matches_table_footer` | `5f0c53a` |
| `templates/` (pacote) + `controle_ocorrencias.py` — grade 5 colunas × 9 linhas, variantes A/B/C (C deslocada, só test via `TEST_ONLY_VARIANTS`), strikethrough `[risc:…]`, rabisco ilegível → `[ilegível]`, rodapé "Ronda" único, `RenderResult(image, ideal_lines, font_name)` | `fef0339` |
| `test_template_controle.py` — 17 testes: `test_ideal_transcription_parses_all_variants` (4 cenários × 3 variantes, estrutura + cabeçalho exato), determinismo, variantes divergem, ilegível, riscado sem texto | `5755a6c` |

Evidência PR-D3: `make check` → **541 passed, 1 skipped**; `make privacy-check` OK.
Armadilha real achada e cercada na D3: o parser fecha a tabela no 1º `\bronda\b` —
o banco da D2 tinha "Ronda" como item/descrição/ação e teria matado o G-S0; agora o
rodapé é o ÚNICO lugar com a palavra, e um teste congela isso.

| **PR-D4** `degrade.py`: `degrade_photo` (perspectiva QUAD, corte ≤3% c/ resize, sombra lateral, downscale espelhado, blur, JPEG) + `Band`/`_banded` 80/20; `degrade_scan(band=None)` preserva o caminho legado EXATO (randint do JPEG mantido — tier_b byte-idêntico) | `0ad03be` |
| `test_degrade_photo.py` — 6 testes: determinismo, dimensões, legibilidade mínima na banda dura (≥50% da tinta), foto≠scan, legado intacto, `test_degrade_bands_disjoint_by_split` (G-S3) | `c953303` |

Evidência PR-D4: `make check` → **547 passed, 1 skipped**; `make privacy-check` OK.
Nota de design D4: bandas "duras" espelham intervalos onde menor = pior (qualidade
JPEG, fator de downscale) para que upper20 seja SEMPRE a fatia mais difícil.

| **PR-D5** guard de samples aceita `sample_tc-*` + teste | `0a0f048` |
| `tier_c.py` — build folha→disco (split ANTES da geração p/ vocab held-out; variante C só test 25%; banda por split; PNG canônico hasheado, PDF derivado; gt canônico SEM `source_file` no hash — decisão: caminho é metadado de armazenamento, não conteúdo) + `CANONICAL_DATASETS` + `check_or_write_frozen` | `edce6fd` |
| `test_tier_c.py` — 6 testes: arquivos, regeneração reproduz sha256, gt shape, held-out e2e, `test_frozen_manifest_matches_regeneration`, tabela canônica congelada | `d365060` |
| fix: rótulos impressos em ASCII (Pillow default sem Ê/ç/ã — tofu MEDIDO na amostra; `Descricao`/`Acao` ⊂ ocr_aliases) | `3776992` |
| `scripts/gen_sheets.py` + Make `gen-sheets DATASET=smoke\|bench-balanced\|bench-operational\|stress` | `cd5ce40` |
| `samples/sample_tc-00000{0,1}.png` (inspeção visual feita: manuscrito com acentos OK, grade, S/A, rodapé) | `bc497a5` |

Evidência PR-D5: `make gen-sheets DATASET=smoke` REAL → "Wrote 50 sheets ... train: 35 / val: 7 / test: 8";
`make check` → **554 passed, 1 skipped**; `make privacy-check` OK (com PNGs tier_c commitados).

| **PR-D6** `load_curadoria(directory, valid_status)` backward-compatible (default inalterado; 36 testes do eval real intactos) | `459d89e` |
| `evals/eval_extraction_synthetic.py` — reusa fórmulas §2 (`run_sheet`, `_norm`, cer≤0.5), lê `gt/` com `valid_status={"synthetic_ground_truth"}`, replay determinístico do extractor sobre a transcrição → false/missed incident, acurácia por campo em TODAS as linhas, recusa correta, CER vs surface; `reader_metrics` separado de `parser_ceiling`; breakdown difficulty × template; público = agregados apenas gateado por `scan_text_for_pii` | `5985d1f` |
| Make `eval-synthetic VISION/DPI/REAL_N/SPLIT` (`SPLIT ?= val` anti-tuning) | `7883d8e` |
| `tests/test_eval_synthetic.py` — 7 testes: **G-S1 nomeado** (`test_smoke_50_mock_no_false_incident`: 50 folhas, zero false_incident), split val default + público aggregates-only sem PII, `--split test` explícito, split inválido rejeitado, dataset ausente → exit 1, recusa premiada (não recuperação) | `9e24ad7` |
| `docs/eval_synthetic_summary.json` — nascimento honesto da rodada mock smoke/val | `78a8a0e` |
| Review Python pós-D6 (agente): 0 CRITICAL/HIGH, 2 MEDIUM corrigidos — guard `--dpi>0` (mesmo padrão do eval real) + `meta.json` corrompido não aborta o run | `3797cb9` |

Evidência PR-D6 (comando real `make eval-synthetic VISION=mock`):
`dataset=smoke split=val reader=mock dpi=150 n=7 ran=7` /
`parse_table_success_rate=0.0 chars_to_type=644 false_incident=0 descricao_acc=0.0 hora_acc=0.0`
(reproduz byte-a-byte a rodada da sessão anterior — determinismo confirmado após o merge).
`make check` → **561 passed, 1 skipped**; `make privacy-check` OK.
Nota: mock não lê imagem ⇒ acurácias 0.0 são o esperado; o valor do run é o G-S1
(S/A nunca vira ocorrência) e o harness pronto para `local_ocr`/`local_vlm`.

## Rodadas reais G-S2 (primeira medição = régua)

> **Disciplina do contrato (§10):** primeira rodada medida — **estabelece a régua**;
> NENHUM pass/fail declarado aqui; alvo numérico só será congelado em rodada
> subsequente. Lembrete permanente: handwriting por fonte TTF é mais fácil que real
> ⇒ números sintéticos são **limite superior otimista**.

### Rodada 1 — Tesseract (`local_ocr`) — 2026-07-06

Ambiente: Tesseract 5 de `C:\Program Files\Tesseract-OCR` (fora do PATH; PATH ajustado
na sessão). Pack `por` **instalado** em tessdata de usuário
(`%LOCALAPPDATA%\Tesseract-OCR\tessdata`, via `TESSDATA_PREFIX` — Program Files sem
admin); `tesseract --list-langs` → eng, osd, **por** ⇒ rodada rodou com `lang=por`
(sem fallback `eng`).

Comando real `make eval-synthetic VISION=local_ocr DPI=150` (split=val default):

```
dataset=smoke split=val reader=local_ocr dpi=150 n=7 ran=7
parse_table_success_rate=0.1429 chars_to_type=845 false_incident=0 descricao_acc=0.0 hora_acc=0.1
```

`reader_metrics` (de `docs/eval_synthetic_summary.json`, commit desta rodada):
missed_incident=1, correct_refusal_rate=1.0, CER vs surface (média)=0.9814.

| by_difficulty | n_ran | parse_ok | chars_to_type | false_inc | missed_inc | hora_acc | CER vs surface |
|---|---|---|---|---|---|---|---|
| clean | 1 | 0.0 | 134 | 0 | 0 | 0.0 | 0.7592 |
| scan  | 5 | 0.2 | 651 | 0 | 0 | 0.1429 | 1.0651 |
| photo | 1 | 0.0 | 60  | 0 | 1 | 0.0 | 0.7846 |

Leitura honesta: Tesseract mal lê o manuscrito TTF (CER ~1 em scan; CER>1 = mais
inserções que texto), mas **false_incident=0 se mantém com leitor real** (G-S1
continua de pé fora do mock) e a recusa correta em campo ilegível foi 1.0. O valor
da rodada é ser a **primeira linha de base medida** do G-S2, não um resultado bom.

### Rodada 2 — VLM local (`local_vlm`, qwen2.5vl:3b via Ollama) — 2026-07-06

Ambiente: Ollama local (`localhost:11434`), modelo `qwen2.5vl:3b`; DPI 100 (150
estoura VRAM — decisão congelada). Duração real: ~21 min p/ 7 folhas (~180 s/folha,
consistente com os ~177 s/folha medidos no eval real).

Comando real `make eval-synthetic VISION=local_vlm DPI=100 REAL_N=30` (--n 30 não
corta nada: smoke/val tem 7 folhas):

```
dataset=smoke split=val reader=local_vlm dpi=100 n=7 ran=7
parse_table_success_rate=0.4286 chars_to_type=1371 false_incident=0 descricao_acc=0.0 hora_acc=0.2
```

`reader_metrics` (de `docs/eval_synthetic_summary.json`, commit desta rodada):
missed_incident=0, correct_refusal_rate=1.0, CER vs surface (média)=1.1343.

| by_difficulty | n_ran | parse_ok | chars_to_type | false_inc | missed_inc | hora_acc | CER vs surface |
|---|---|---|---|---|---|---|---|
| clean | 1 | 0.0 | 228 | 0 | 0 | 0.0 | 0.9755 |
| scan  | 5 | 0.4 | 1102 | 0 | 0 | 0.1429 | 1.2145 |
| photo | 1 | 1.0 | 41  | 0 | 0 | 1.0 | 0.8923 |

Comparação direta com a Rodada 1 (mesmas 7 folhas, sem pass/fail): o VLM parseia a
estrutura da tabela melhor (0.4286 vs 0.1429) e não perde ocorrência (missed 0 vs 1),
mas **gera mais texto errado para corrigir** (chars_to_type 1371 vs 845) e CER maior
(1.1343 vs 0.9814 — CER>1 = inserções/alucinação de texto). Nenhum leitor lê o
manuscrito TTF de fato (descricao_acc=0.0 em ambos). **false_incident=0 nos dois
leitores reais** — o invariante de segurança segue de pé. Régua G-S2 estabelecida;
alvo numérico e escolha de leitor ficam para a calibração G1-S (val→congela→test).

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
git log --oneline -20          # commits da tabela acima (branch SSI-1002-tier-c-eval)
make check                     # deve estar verde antes de qualquer mudança (561+ testes)
# A FÁBRICA (D0–D6) ESTÁ COMPLETA. Próximos passos, nesta ordem:
#   1. Rodadas reais de leitor no smoke/val: make eval-synthetic VISION=local_ocr DPI=150
#      e VISION=local_vlm DPI=100 REAL_N=30 (subamostra seedada; ~177 s/folha medido).
#      Publicar agregados; NENHUM alvo numérico antes da primeira rodada (G-S2).
#   2. Calibração G1-S em val (DATASET_CONTRACT.md §10): escolher leitor/dpi em val,
#      CONGELAR, rodar test UMA vez, registrar aqui + no contrato.
#   3. Gerar bench-balanced (300/seed43) e bench-operational (300/seed44):
#      make gen-sheets DATASET=bench-balanced etc.; commitar manifests congelados.
#   4. (futuro) stress 1000/seed45; segunda família de template exige config YAML nova antes.
# Lembretes permanentes: micro-commits autor JoaoMiltzarek, nunca push,
# atualizar ESTE arquivo ao fim de cada micro-passo, make privacy-check após docs.
```
