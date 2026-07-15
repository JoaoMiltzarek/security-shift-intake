# EVAL_PROTOCOL — a régua que decide o VLM local (PR-1)

> Documento **normativo**. Toda métrica publicada por `evals/eval_extraction_real.py`
> segue as fórmulas daqui; qualquer relatório que cite um número desta régua cita este
> protocolo. Se código e protocolo divergirem, o protocolo manda — corrija o código.
> Nenhum número é digitado à mão (CLAUDE.md, invariante #3).

> **⚠️ Reposicionamento (decisão registrada em `DATASET_CONTRACT.md` §1):** a régua
> **oficial** do projeto passou a ser o dataset sintético `tier_c` (gates G-S0…G-S3 e
> **G1-S**) + BRESSAY + públicos licenciados — nenhuma decisão de roadmap depende mais
> de folha real. Os gates **G1–G3 abaixo (§3) são legado / avaliação local opcional**,
> apenas com folhas 100% autorizadas, locais e nunca versionadas. As **fórmulas do §2
> permanecem normativas** — são exatamente as que o eval sintético reusa.

## 0. A pergunta que este protocolo responde

**O VLM local reduz esforço humano em folha real?** Medido por
`estimated_chars_to_type` (proxy parcial primário), `parse_table_success`, `tempo_por_folha` e a
comparação **pareada por campo** contra a curadoria — nunca por CER isolado em dataset
de terceiros (BRESSAY é sanity check, papel secundário; ver `docs/EVAL_BRESSAY.md`).

## 1. Mapping do cabeçalho (normativo — sem gambiarra)

Os três campos escalares `required: true` da config `configs/controle_ocorrencias.yaml`
mapeiam assim (config → curadoria → modelo normalizado):

| campo da config | curadoria (`private/curadoria/*.json`) | normalizado (`NormalizedIncidentModel`) |
|---|---|---|
| `data_turno` | `cabecalho.data` | `normalized.shift.date` |
| `vigilantes` | `cabecalho.vigilantes` (lista → join `", "`) | `normalized.shift.guards` (lista → join `", "`) |
| `unidade` | `cabecalho.unidade` | `normalized.shift.unit` |

O código deriva a lista de campos da config (escalares `required: true`), e usa esta
tabela para achar o valor curado e o valor do sistema. Campo novo na config entra na
régua ao ganhar uma linha aqui — não num `if` solto.

**Campos comparáveis** de uma folha = os escalares do mapping acima **+**
`ocorrencia_1_descricao` (= `ocorrencias[0].descricao` na curadoria ×
`normalized.occurrences[0].description` no sistema), presente só quando a curadoria tem
ocorrência. **Limitação declarada:** folhas com múltiplas ocorrências têm o esforço
medido só no cabeçalho + 1ª ocorrência; estender quando existir folha curada
multi-linha (hoje o conjunto tem ≤ 1 ocorrência por folha — o comportamento multi-linha
é métrica limitada, dito aqui, não escondido).

## 2. Fórmulas exatas

Normalização de texto (`_norm`): minúsculas, sem acento, espaços colapsados — a mesma
de `evals/eval_extraction_real.py`. `cer`/`levenshtein` vêm de `evals/metrics.py`.
**Acerto** de um campo = `cer(_norm(curado), _norm(sistema)) ≤ 0.5` com ambos não-vazios.

### 2.1 `parse_table_success` (por folha, bool)

Verdadeiro sse **todas**:

1. `normalized.disposition == ("present" if has_occurrence(curadoria) else "none")` —
   o tri-state é a fonte de verdade; `unknown` nunca conta como parse correto;
2. `header_minimum_present` — **todos** os escalares `required: true` (mapping §1)
   não-vazios no normalizado;
3. `row_count_error ≤ 0` (tolerância default **0**), onde
   `row_count_error = |len(curadoria.ocorrencias quando has_occurrence, senão 0) − len(normalized.occurrences)|`;
4. quando `has_occurrence(curadoria)`: `occurrences_represented ≥ 1` (a 1ª ocorrência
   curada tem uma linha onde existir no normalizado).

### 2.2 Esforço humano (o valor real do VLM pode ser "não acerta tudo, mas reduz digitação")

`estimated_chars_to_type` is a **partial human-effort proxy**, not total review effort:
no eval real atual ele cobre os campos obrigatórios do cabeçalho e a primeira ocorrência
comparável. Não inclui adicionar/remover linhas, revisar classificação/roteamento nem corrigir
as demais ocorrências de uma folha multi-linha.

Por campo comparável (§1):

- `estimated_chars_to_type` = `len(_norm(curado))` se o sistema veio em branco;
  senão `levenshtein(_norm(sistema), _norm(curado))`. **Métrica primária** = soma por folha.
- `prefilled_but_wrong_count` = nº de campos com curado e sistema não-vazios e
  `cer > 0.5`.
- `blank_field_count` = nº de campos com curado não-vazio e sistema em branco.
- `illegible_token_count` = nº de ocorrências literais de `[ilegível]` na transcrição.
- `campos_corrigidos_por_folha` = `prefilled_but_wrong_count + blank_field_count`
  (erro grosseiro; **secundária** — a primária de esforço é `estimated_chars_to_type`).

### 2.2.1 Recusa segura de campo ilegível (somente Tier C sintético)

- `safe_illegible_refusal_rate = safe_illegible_refusals / illegible_fields`.
- Uma recusa conta somente quando **not recovered AND review signaled AND operational_approvable=false**:
  não recuperar a verdade limpa é necessário, mas insuficiente;
  a linha precisa sinalizar revisão (ou a disposição ser `unknown`) e o estado realmente executado
  deve estar bloqueado para aprovação.
- Sem campo ilegível plantado, o valor é `null`; a métrica nunca é usada para inferir `S/A`.

### 2.3 Probe de repairability (decide a forma da PR-2, sem implementá-la)

- `repairable_ratio` = |campos `must_review` com `bbox ≠ None` **e** `page ≠ None`| ÷
  |campos `must_review`|. Caso 0/0 → **`null`** (indefinido; nunca 1.0).
- `missing_count` = nº de campos com status `missing`.

### 2.4 Tempo e confiança

- `tempo_por_folha` (`elapsed_sec`) = wall-clock de `run_pipeline` por folha
  (`time.monotonic`), excluindo carregamento de curadoria.
- `confidence_source` = **lido de `TranscriptionResult.confidence_source`**
  (`logprobs | placeholder | tesseract | mock`), propagado ao estado do pipeline.
  Nunca inferido pelo eval.

### 2.5 Comparação pareada por campo (o formato que sustenta G1 com n pequeno)

Entre duas rodadas (baseline × VLM) sobre as **mesmas folhas**: para cada campo
comparável, resultado ∈ {`both`, `only_baseline`, `only_vlm`, `neither`}
(acerto = §2 acima). Publicado por índice anônimo (`sheet_1.data_turno`), nunca por
valor.

## 3. Gates de decisão (numéricos) — **LEGADO / avaliação local opcional**

> Estes gates dependem de folha real curada e **não são mais requisito de nenhuma PR**
> (ver reposicionamento acima). Quem tiver folhas 100% autorizadas e locais pode
> avaliá-los como verificação complementar; a decisão oficial é o **G1-S**
> (`DATASET_CONTRACT.md` §10).

- **G1 (escalonamento de página → PR-2).** Todas:
  1. **Taxa agregada, não boolean solto:**
     `mean(parse_table_success_vlm) ≥ mean(parse_table_success_baseline)` sobre as
     mesmas folhas — equivalente, no pareado, a
     `vlm_success_count ≥ baseline_success_count`;
  2. vitória pareada por campo: `only_vlm > only_baseline` com **margem ≥ 2 campos**
     (com n≈4 folhas, diferença de 1 campo é ruído);
  3. redução do total de `estimated_chars_to_type` (VLM < baseline);
  4. `tempo_por_folha` ≤ **SLO** declarado pelo usuário (§5 — registrado aqui antes
     de avaliar o gate).
- **G2 (reparo por recorte → PR-2b).** `repairable_ratio ≥ 0.8` nos pendentes.
  Se `missing` domina os pendentes (`missing_count > must_review_count`), a PR-2
  compara **página inteira VLM × crop por região fixa** (o rótulo impresso ancora a
  região em layout fixo) antes de qualquer decisão de matar o reparo.
- **G3 (calibração/threshold → PR-3).** Pelo menos um leitor com
  `confidence_source = "logprobs"` **lido do campo do schema** — e, mesmo assim,
  nenhuma decisão de threshold com menos de **50 campos comparados**.

## 4. Honestidade estatística (mínimos)

- `< 10` folhas `verified_by_user` → o relatório inteiro é **DIRECIONAL** (gates
  avaliáveis, decisão anotada como provisória).
- `< 50` campos comparados → **nenhuma decisão de threshold** (G3 bloqueado mesmo
  com logprobs).
- O relatório imprime sempre `n` de folhas e `n` de campos.
- Curadoria `draft_by_claude`/`needs_review` conta como **PRELIMINAR**, nunca como
  número oficial (regra já vigente no eval).
- A alavanca mais barata do projeto é humana: **mais folhas curadas
  `verified_by_user`** valem mais que qualquer código desta PR.

## 5. SLO de tempo por folha

`tempo_por_folha` alvo: **≤ 300 s/folha** (congelado em `configs/controle_ocorrencias.yaml`
→ `performance.max_seconds_per_sheet: 300`, branch SSI-1003). G1.4 pode ser avaliado
contra esta margem; nenhuma decisão de threshold antes deste número.

## 6. Artefatos com nome fixo

| artefato | caminho | conteúdo |
|---|---|---|
| Detalhado (PII) | `private/audit/eval_real_detailed_{reader}_dpi{dpi}.json` | tudo, por folha, inclusive transcrição/valores. Substitui `metrics_real.json` como fonte detalhada das rodadas instrumentadas. Gitignored. |
| Resumo local allowlisted | `private/audit/eval_real_summary.json` | Construído por whitelist (§7): uma entrada por rodada `(reader, dpi)` + seção `paired`; gitignored. |
| Público histórico | `docs/eval_real_summary.json` | Historical, directional, pre-runtime-attestation diagnostic; not release evidence e nunca sobrescrito pelo evaluator atual. |
| Compare legado local | `private/audit/AUDITORIA_FOLHAS_REAIS.md` | ANTES escalar × DEPOIS tabela (modo `--legacy-compare`); o relatório histórico em `docs/` é preservado. |

**Fronteira de publicação:** rodadas novas nascem somente em `private/audit/`. O evaluator não
publica nem atualiza arquivos em `docs/`. O JSON versionado atual é histórico e anterior à
atestação completa de Python/lock/Tesseract; seus números não comprovam o HEAD atual. O exemplo
de schema em §7 é **exemplo**, não evidência.

Contract: evaluators never write directly to `docs/`; publication is a separate write-once operation.
O inventário verificável está em `docs/evals/catalog.json` e a promoção autenticada da v1 em
`docs/EVAL_RELEASE.md`.

## 7. Schema público sanitizado (whitelist — nunca subtração)

O JSON público contém **somente**:

- metadados de rodada: `reader`, `model` (tag/digest best-effort via `/api/tags`,
  `"unknown"` se indisponível), `dpi`, `prompt_sha256`, `git_commit`, `timestamp`,
  `python_version`, `python_version_expected`, `uv_lock_sha256`, `tesseract_version`,
  `tesseract_language`, `runtime_attested`, `n_sheets`, `n_sheets_ran`,
  `n_verified_by_user`, `n_fields_compared`;
- métricas agregadas e por folha **anônima** (`sheet_1`, ordem = `document_id`
  ordenado): `parse_table_success`, `must_review_count`, `missing_count`,
  `repairable_ratio`, `estimated_chars_to_type`, `prefilled_but_wrong_count`,
  `blank_field_count`, `illegible_token_count`, `campos_corrigidos_por_folha`,
  `n_fields_compared`, `elapsed_sec`, `ocr_quality`, `confidence_source`, `available`;
- para folha indisponível, `reason` é sempre um safe allowlisted reason code:
  `pending_file`, `reader_error`, `source_outside_private` ou `unavailable`; texto de exceção
  nunca entra no resumo;
- pareado por índice anônimo de campo: `sheet_1.data_turno → only_vlm` etc.

**Proibidos** (ficam só no detalhado em `private/audit/`): transcrições, valores de
campo, caminhos/nomes de arquivo, nomes de unidade/pessoas, `document_id`
correlacionável. Implementação: o eval **constrói** o público pela whitelist (nunca
remove campos de um objeto maior), e `scan_text_for_pii` roda como **segunda camada**
antes de escrever.

Exemplo ilustrativo (EXEMPLO, não evidência):

```json
{
  "runs": [
    {
      "reader": "local_vlm", "model": "qwen2.5vl:3b sha256:abc...", "dpi": 150,
      "prompt_sha256": "…", "git_commit": "…", "timestamp": "…",
      "n_sheets": 4, "n_sheets_ran": 4, "n_verified_by_user": 0, "n_fields_compared": 14,
      "aggregate": {"parse_table_success_rate": 0.75, "estimated_chars_to_type_total": 210},
      "per_sheet": [{"sheet": "sheet_1", "parse_table_success": true, "elapsed_sec": 41.2}]
    }
  ],
  "paired": {
    "baseline": {"reader": "local_ocr", "dpi": 150}, "vlm": {"reader": "local_vlm", "dpi": 150},
    "fields": {"sheet_1.data_turno": "only_vlm"},
    "counts": {"both": 3, "only_baseline": 1, "only_vlm": 6, "neither": 4}
  }
}
```

## 8. Failure matrix — cada linha é um teste nomeado, não uma promessa

| Falha | Comportamento esperado | Teste |
|---|---|---|
| Ollama offline / modelo não baixado / timeout | `RuntimeError` capturado pelo eval → folha `available:false` com motivo; rodada não morre; coluna baseline (rodada separada) intacta | `test_eval_marks_vlm_runtime_error_available_false` |
| VLM devolve vazio/sem texto | `_parse_text` levanta → mesmo tratamento; string vazia válida → `ocr_quality=failed` (<30 chars), folha registrada | `test_eval_vlm_empty_response_degrades_not_crashes` |
| VLM devolve markdown/fora do contrato | `extract_table` degrada para must_review/failed, **nunca inventa** ocorrência aceita | `test_vlm_contract_markdown_degrades_to_review` |
| PII plantada no estado | whitelist do público a exclui **por construção** | `test_public_report_whitelist_drops_pii` |
| DPI/vision inválidos | argparse rejeita com mensagem clara | `test_invalid_dpi_rejected`, `test_invalid_vision_rejected` |
| Tesseract ausente | caminho existente: folha com erro de leitor, motivo registrado | `tests/test_eval_extraction_real.py` (existente) |
| Curadoria ausente/inválida | exit 1 / folha ignorada | existente |
| BRESSAY ausente | `available:false` com motivo | `tests/test_eval_bressay.py` (existente) |
| PII detectada no relatório final | aborta com exit 2, não escreve | existente (segunda camada) |

## 9. Invariantes de contrato (desta e das próximas PRs)

- **Erro do VLM nunca apaga o baseline.** PR-1: capturado por folha no eval.
  PR-2: capturado no orquestrador, com retenção do resultado baseline.
- **Nenhum número manual**; `available:false` quando faltar dependência.
- **PII nunca fora de `private/`** (gate existente + whitelist §7).

## 10. Protocolo de rodada local (gera os números dos gates)

```bash
# 0. pré-requisito humano: curadorias → verified_by_user (docs/CURADORIA_FORMATO.md)
ollama serve && ollama pull qwen2.5vl:3b
uv run --locked python -m scripts.build_bressay_manifest --bressay-dir datasets/bressay --n 20
make eval-bressay N=20                                   # sanity: o leitor lê manuscrito pt-BR?
make eval-real VISION=local_ocr DPI=150                  # baseline instrumentado
make eval-real VISION=local_vlm DPI=150                  # a medição que decide
make eval-real VISION=local_vlm DPI=250                  # sensibilidade a DPI
# pareado (G1):
uv run --locked python -m evals.eval_extraction_real --compare \
  private/audit/eval_real_detailed_local_ocr_dpi150.json \
  private/audit/eval_real_detailed_local_vlm_dpi150.json
```
