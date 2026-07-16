# DATASET_CONTRACT — fábrica sintética `tier_c` (folha "Controle de ocorrências")

> Documento **normativo**. Todo artefato gerado pela fábrica (`data/generators/tier_c.py`,
> quando existir) e todo número publicado pelo eval sintético
> (`evals/eval_extraction_synthetic.py`) seguem este contrato. Se código e contrato
> divergirem, o contrato manda — corrija o código. Nenhum número é digitado à mão
> (CLAUDE.md, invariante #3). Horas em exemplos deste documento são sempre o
> placeholder `HH:MM` (nunca horários reais — gate de privacidade).

## 0. Papel e escopo (o que este dataset mede — e o que NÃO mede)

**Mede:** robustez de **leitura + parse sob degradação visual** da folha de tabela
"Controle de ocorrências" (config `configs/controle_ocorrencias.yaml`), com verdade
perfeita e barata em escala (50–1000 folhas), 100% fictícia e reproduzível por seed.

**NÃO mede (circularidade declarada):**
- O renderer escreve os rótulos que o parser (`src/clients/table_rules.py`) procura →
  `parse_table_success` em folha limpa é **parcialmente circular por construção**.
  Mitigação: variantes de layout + held-out em 4 dimensões (§5) + gate G-S0 separado das
  métricas de leitor (§10). A circularidade não desaparece; ela é declarada e cercada.
- Fonte TTF handwriting ≠ cursiva humana real. Números sintéticos são **limite superior
  otimista**; é proibido apresentá-los como comparáveis a desempenho em folha real.
  O diagnóstico direcional de manuscrito PT-BR vem do **BRESSAY**
  (`docs/EVAL_BRESSAY.md`), não da fonte TTF; ele é secundário e non-blocking.

## 1. A régua oficial (decisão registrada)

Nenhuma folha real da empresa é usada nem como dado nem **como régua de decisão**
(invariante #2). A régua oficial do projeto passa a ser:

1. **`tier_c`** (este contrato) — gates G-S0…G-S3 e **G1-S** (§10);
2. **BRESSAY** — diagnóstico secundário e non-blocking de manuscrito PT-BR real;
3. datasets públicos de formulário **se licenciados** (§8).

Os gates G1–G3 sobre folhas reais curadas (`docs/EVAL_PROTOCOL.md` §3) viram **legado /
avaliação local opcional** — apenas com folhas 100% autorizadas, locais e nunca
versionadas; nunca requisito do roadmap. As **fórmulas** do protocolo (§2 de
`EVAL_PROTOCOL.md`) permanecem normativas e são as mesmas usadas aqui.

## 2. Schema do gabarito (uma folha = um JSON)

O gabarito usa o **formato da curadoria** (`docs/CURADORIA_FORMATO.md`) + um bloco
`synthetic`. Assim `load_curadoria`/`run_sheet`/fórmulas de
`evals/eval_extraction_real.py` funcionam sem segunda pilha de métricas.

### 2.1 Exemplo (folha S/A; horas sempre `HH:MM` em docs)

```json
{
  "schema_version": "1.0",
  "document_id": "tc-000017",
  "source_file": "data/synthetic/tier_c/pdfs/tc-000017.pdf",
  "review_status": "synthetic_ground_truth",
  "truth_source": "generator",
  "cabecalho": {
    "data": "14/03/2026 - Noite",
    "turno": "Noite",
    "vigilantes": ["B. Lima", "K. Gomes"],
    "unidade": "Unidade 07"
  },
  "sem_alteracao": true,
  "riscado": false,
  "ocorrencias": [],
  "synthetic": {
    "generator": "tier_c/v1",
    "seed": 42,
    "template": "controle_A",
    "profile": "balanced",
    "difficulty": "scan",
    "font": "Caveat-Regular",
    "messiness": [],
    "legibility": {},
    "surface": {}
  }
}
```

Com ocorrências: mesmo shape, `sem_alteracao: false`, 1..3 entradas
(`{"item": "Ambulância", "hora_entrada": "HH:MM", "hora_saida": "HH:MM",
"descricao": "...", "acao": "...", "resolvido": "sim"}`).

### 2.2 Invariantes do gabarito

- **`cabecalho.data` = exatamente a string desenhada** no campo "Data e Turno"
  (ex.: `"14/03/2026 - Noite"`), nunca só a data — a régua compara `data_turno`
  (sistema) × `cabecalho.data` (gabarito) por CER; gabarito só com a data geraria
  OCR_MISS falso em toda folha. `turno` fica separado como informação estruturada
  (a curadoria permite: "turno, se separável"). Teste de serialização (PR-D2) afirma isso.
- **`review_status: "synthetic_ground_truth"`** = verdade **gerada**. Nunca significa
  verificação humana, nunca aparece em `private/curadoria/`, e o eval real a ignora por
  default. `truth_source ∈ {human_curation, generator}` torna a origem explícita mesmo
  se alguém copiar o arquivo de lugar. Semântica formal em `docs/CURADORIA_FORMATO.md`.
- **Duas vistas por folha** (padrão de `data/generators/tier_b.py`): a curadoria carrega
  a **verdade limpa**; `synthetic.surface` carrega o **desenhado** (com messiness),
  `synthetic.messiness` lista as ops aplicadas (`"crossout:ocorrencias[0].descricao"`,
  `"blank:ocorrencias[0].acao"`, …) e `synthetic.legibility` marca campos por legibilidade.
- **Regra de avaliação da messiness:** campo `legibility: "illegible"` ⇒ correto =
  **recusa segura** (não recuperado + sinal de revisão + aprovação operacional bloqueada),
  publicada como `safe_illegible_refusal_rate`; campo em branco no papel ⇒ correto =
  `missing`. Nunca premiar recuperação do irrecuperável — seria premiar alucinação.
  Extração compara contra a verdade limpa; transcrição (CER/WER) contra `surface`.

## 3. Estrutura de pastas, versionamento e hash

```
data/synthetic/tier_c/            # gitignored (regenerável por seed)
  pdfs/tc-000000.pdf …            # 1 página por folha
  pngs/tc-000000.png               # entrada canônica com integridade validada
  gt/tc-000000.json               # gabarito (§2)
  manifests/{train,val,test}.jsonl
  meta.json
data/manifests/tier_c_manifest_v2/
  bench-balanced.val.jsonl        # COMMITADO: freeze do gate da release
data/manifests/tier_c_v1_bench_balanced_test.jsonl     # historical test freezes
data/manifests/tier_c_v1_bench_operational_test.jsonl  # historical test freezes
assets/fonts/                     # COMMITADO: .ttf OFL + OFL.txt + FONTS.md (registro)
samples/sample_tc-000000.png …    # COMMITADO: 2–3 amostras (guard estendido, PR-D5)
```

- **Dois versionamentos independentes:** o conteúdo gerado permanece `tier_c/v1`; o contrato
  estrito do manifesto é `tier_c-manifest/v2`. Mudança de vocabulário/layout/degradação exige
  novo dataset `tier_c/vN`; mudança do envelope/validação exige novo manifest schema. Nunca
  "ajustar hash na mão".
- **Política de hash (manifest schema v2):** cada linha canônica contém exatamente
  `{"doc_id", "split", "image", "gt", "sha256_img", "sha256_gt"}`, em que
  `"image": "pngs/<doc_id>.png"` e `gt` segue `gt/<doc_id>.json`. Campos extras, paths
  absolutos, `..`, ids fora do padrão, duplicatas e contagens divergentes são recusados antes
  de construir o reader.
  `sha256_gt` = JSON canônico (chaves ordenadas, `ensure_ascii=False`, separadores fixos);
  `sha256_img` = bytes **PNG** da página degradada — **nunca o PDF** (o writer PDF do
  Pillow embute metadados de criação que quebram reprodutibilidade; o PDF é artefato
  derivado, não hasheado).
- **Caveat de toolchain (declarado):** os sha256 de imagem valem **sob o ambiente do
  `uv.lock`** (rasterização depende de Pillow/FreeType). O teste de regeneração falha com
  mensagem apontando drift de toolchain; upgrade que mude a rasterização ⇒ bump `tier_c/vN`.
- **Freeze autoritativo da release:** `bench-balanced/val`, 45 entradas, em
  `data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl`; SHA-256 canônico
  `aa317c587a71e51c7352dd1379412a1e00c222494e3e112f038256ab316986bd`. O arquivo é
  write-once: `scripts.freeze_tier_c_manifest` aceita bytes idênticos e recusa sobrescrita.
- **meta.json v2:** `{"manifest_schema", "version", "dataset", "seed", "split_seed", "n",
  "profile", "counts", "heldout_vocab_seed", "heldout_fractions", "heldout_bands",
  "git_commit"}`; `manifest_schema` deve ser `tier_c-manifest/v2`.

## 4. Datasets canônicos `tier_c/v1` (fixos)

| Nome | N | seed | profile | split_seed | Papel | Manifesto congelado |
|---|---|---|---|---|---|---|
| `smoke` | 50 | 42 | balanced | 0 | G-S1, iteração de dev; descartável | não |
| `bench-balanced` | 300 | 43 | balanced | 0 | **benchmark oficial** (G-S2, G1-S; gate atual em val) | `data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl` |
| `bench-operational` | 300 | 44 | operational | 0 | prior operacional; FALSE_INCIDENT sob prior real | freeze v1/test histórico; não é gate da release atual |
| `stress` | 1000 | 45 | balanced | 0 | robustez em escala; **só mock/tesseract** | não |

A tabela vive em código (`data/generators/tier_c.py::CANONICAL_DATASETS`) e aqui;
`make gen-sheets DATASET=<nome>` resolve N/seed/profile dela. Toda rodada de eval imprime
`dataset + split`; todo número publicado cita qual dataset canônico o produziu.

## 5. Splits e held-out (anti-memorização — gate G-S3)

- **Ids disjuntos:** `data/generators/tier_a.py::split_dataset`, ratios 70/15/15.
- **Held-out obrigatório em 4 dimensões** (frações registradas em
  `meta.json.heldout_fractions` / `heldout_bands`):
  1. **Vocabulário:** ~20% dos nomes de vigilante e ~20% das unidades existem SÓ no test;
  2. **Templates de frase:** ~20% dos templates de descrição-ação existem SÓ no test;
  3. **Layout:** variantes A e B em todos os splits; **variante C só no test** (~25% dos
     docs do test);
  4. **Degradação:** train/val amostram dos **80% inferiores** de cada intervalo bounded;
     os **20% superiores** (banda mais dura, ainda mild) são exclusivos do test.
- **Anti-tuning (mecanismo, não só declaração):** o eval sintético roda em `val` por
  default; `--split test` é ato explícito e o relatório imprime o split usado. **É
  proibido usar o test congelado para prompt tuning.** Ajustou prompt/limiar olhando o
  test ⇒ o número está contaminado e não pode ser publicado como G1-S.

## 6. Perfis de distribuição

| Perfil | S/A | Com ocorrências | Uso |
|---|---|---|---|
| `balanced` (default) | ~50% | ~50% (1–3 linhas) | eval — mais sinal por folha |
| `operational` | ~70% | ~30% | simular prior operacional real; FALSE_INCIDENT sob prior real |

Priors documentados inline em `data/generators/priors.py` (padrão existente, validados
por `validate_all_priors`). Nº de vigilantes: 1–3. Hora dupla (`hora_entrada` +
`hora_saida`) em ~30% das ocorrências com hora.

## 7. Conteúdo fictício por construção

- **Listas fixas revisadas em PR** (nunca geradas por LLM em runtime): nomes
  (`GUARD_NAMES` estendido), unidades (mix "Unidade 01..12" + nomes inventados tipo
  "Posto Delta"), ~18 tipos de item com bancos de descrição/ação (ambulância
  entrada/saída, veículo não autorizado, alarme, falta de energia, porta aberta,
  visitante sem crachá, objeto esquecido, prestador acompanhado, troca de turno, ronda,
  acesso, comunicado…).
- **Placas veiculares:** formato Mercosul gerado aleatoriamente, sem vínculo com pessoa
  ou veículo — fictícias por construção; colisão casual com uma placa existente não cria
  vínculo com ninguém.
- **Higiene de IP:** o template imita a **estrutura genérica** (cabeçalho + tabela de 5
  colunas + S/A), **nunca** reproduz a arte/diagramação exata do formulário da empresa.
- **Datas:** ano sintético (época fixa em `data/generators/records.py::_EPOCH`).
- `make privacy-check` roda como **segunda camada** em todo artefato público.

## 8. Datasets públicos (papel declarado; regra de entrada)

| Dataset | Usar | NÃO usar |
|---|---|---|
| **BRESSAY** | Ativo: diagnóstico direcional e non-blocking de cursiva PT-BR real (`make eval-bressay`). Futuro opcional: colagem de crops em células — **só após verificar licença** | Como gate de G1-S/release, como métrica isolada de decisão ou como texto de ocorrência |
| **XFUND (subset PT)** | Candidato futuro: sanity de formulário impresso key-value | Fingir que formulário impresso mede manuscrito |
| **NIST SD19** | Candidato futuro: colagem de dígitos handprinted em Hora/Data, se fonte TTF se provar fácil demais | Baixar "por via das dúvidas" |
| **IAM** | **Descartado** (inglês + licença não-comercial) | — |
| **FUNSD / DocLayNet / CORD / SROIE** | **Descartados** (inglês / domínio errado: layout genérico, recibos) | — |

**Regra:** dataset novo só entra com (papel declarado + licença verificada + o que ele
NÃO mede) registrados aqui.

## 9. Escala honesta

Medido nesta máquina (`docs/archive/STATUS_PR1.md`): VLM ≈ 177 s/folha a DPI 100; DPI 150 estoura
a VRAM. Portanto:

- conjunto cheio (300/1000) roda **só com `mock`/`local_ocr`**;
- VLM roda em **subamostra seedada** (ex.: N=30) a **DPI 100**;
- 1000 folhas no VLM ≈ 49 h — **proibido** no conjunto cheio.

## 10. Gates (declarados antes, medidos por código)

| Gate | Critério | Teste nomeado / evidência |
|---|---|---|
| **G-S0** contrato gerador↔parser | `ideal_lines → RuleBasedTableExtractor → normalize` ⇒ `parse_table_success = 100%` no clean (3 variantes). Falhou ⇒ bug de render/parser, não de leitor | `test_ideal_transcription_parses_all_variants` (PR-D3) |
| **G-S1** smoke 50 | pipeline mock roda 50 folhas sem crash; S/A **nunca** vira ocorrência aceita (FALSE_INCIDENT = 0 no mock) | `test_smoke_50_mock_no_false_incident` (PR-D6) + saída real de `make eval-synthetic VISION=mock` |
| **G-S2** régua de leitor | números Tesseract × VLM por dificuldade × variante; **sem alvo pré-fabricado** — alvo entra aqui só após a 1ª rodada medida (disciplina do SLO, `EVAL_PROTOCOL.md` §5) | saídas diagnósticas locais; resultados históricos e freeze inventariados em `docs/evals/catalog.json` |
| **G-S3** anti-memorização | held-out em 4 dimensões (§5) + test congelado (sha256) fora do prompt tuning | `test_heldout_vocab_disjoint`, `test_heldout_templates_disjoint` (PR-D2); `test_variant_c_only_in_test`, `test_degrade_bands_disjoint_by_split` (PR-D3/D4); `test_frozen_manifest_matches_regeneration` (PR-D5); default `--split val` (PR-D6) |
| **G1-S** adoção histórica de leitor (**substituiu o G1 real como régua oficial naquele ciclo**) | no **test do `bench-balanced`**: `parse_table_success_rate ≥ 0.30`; `false_incident_count ≤ 6`; `estimated_chars_to_type ≤ 4000`; `hora_acc ≥ 0.0`. BRESSAY é registrado apenas em `observations_not_thresholded` e não altera o veredito | `scripts/g1s_verdict.py` + `docs/eval_g1s_calibration.json` |

Contract: evaluators never write directly to `docs/`; publication is a separate write-once operation,
validada pelo procedimento em `docs/EVAL_RELEASE.md` e indexada por hash em
`docs/evals/catalog.json`.

**Protocolo de calibração do G1-S:** margens/tolerâncias são calibradas rodando em
`val`, **congeladas neste contrato (via commit)**, e só então avaliadas **UMA vez** em
`test`. Ajustar qualquer alvo depois de olhar o test é proibido — mudança de alvo ⇒ novo
ciclo val → congela → test.

> **Margens G1-S congeladas** (calibradas no `val` de `bench-balanced`, n=45,
> branch SSI-1003; avaliar em `test` UMA vez):
>
> | Métrica | Val (local_ocr) | Val (local_vlm) | Escolha | Limiar para `test` |
> |---------|-----------------|-----------------|---------|-------------------|
> | Leitor adotado | Tesseract 5 | qwen2.5vl:3b | **local_ocr** | — |
> | `parse_table_success_rate` | 0.40 | 0.5556 | — | ≥ 0.30 |
> | `false_incident_count` | **4** | 9 | local_ocr | ≤ 6 |
> | `estimated_chars_to_type` | **3264** | 4902 | local_ocr | ≤ 4000 |
> | `hora_acc` | 0.0714 | 0.3929 | — | ≥ 0.0 |
>
> **Decisão**: local_ocr (Tesseract) preferido — menos false_incidents E menos chars_to_type;
> VLM rejeitado por gerar 9 ocorrências fantasma em folhas degradadas.
>
> **Resultado do test (registrado após UMA rodada; bloco `test_result` em
> `docs/eval_g1s_calibration.json`, escrito por `scripts/g1s_verdict.py` — nunca à mão):**
> **G1-S = REPROVADO** — `parse_table_success_rate` 0.1111 < 0.30 congelado (val 0.40 →
> test 0.1111; o test segura a variante C e bandas de degradação nunca vistas, §5).
> Critérios restantes passaram: `false_incident` 1 ≤ 6; `chars_to_type` 2827 ≤ 4000;
> `hora_acc` 0.0 ≥ 0.0. A observação BRESSAY não-limiarizada registrou Tesseract
> mean_cer 1.0 e qwen2.5vl:3b mean_cer 4.30 (inserções longas em crops de palavra).
> Esse harness histórico não autenticou manifesto versionado, runtime efetivo ou tolerância
> CER predeclarada e, portanto, não prova ausência de regressão. Outra observação
> não-limiarizada foi `missed_incident` 22 (val: 0);
> A rodada histórica não mediu `safe_illegible_refusal_rate`; seu valor de recusa legado
> não é evidência do gate operacional atual e não foi renomeado retroativamente.
> **Consequência**: nenhum leitor custo-zero é adotado como transcritor automático; o
> pipeline permanece ferramenta de triagem com gate humano obrigatório. Adotar um leitor
> novo exige novo ciclo val → congela → test (proibido reusar este test para tuning).

## 11. Detalhes que amarram gerador ↔ eval (cada um vira asserção de teste)

Verificados contra o código atual; sem eles, G-S0 nunca daria 100% ou o eval geraria
OCR_MISS falso sistemático:

1. `cabecalho.data` = string desenhada no campo "Data e Turno" (§2.2). [PR-D2]
2. Vigilantes desenhados com separador dentro de `_GUARD_SEP` (`src/pipeline/normalize.py`)
   e listados iguais no gabarito — os dois lados juntam com `", "`. [PR-D2/D3]
3. `ideal_lines` separa ocorrências por **linha em branco**: `_extract_rows`
   (`table_rules.py`) agrega linhas consecutivas numa única row e só fecha em linha vazia
   ou S/A. [PR-D3]
4. Hora dupla na **mesma célula** (`HH:MM / HH:MM` ou `HH:MM - HH:MM`); `resolvido`
   desenhado como `sim`/`não`. [PR-D3]
5. Honestidade por coluna: o extractor atual é line-based — `item`/`acao`/`resolvido`
   saem `missing` **por construção** (ver §12). [PR-D6]
6. Determinismo testado por **dupla geração no mesmo run** (padrão `test_tier_b.py`),
   nunca golden-hash de imagem commitado em teste — estabilidade entre máquinas é papel
   do manifesto congelado + caveat do `uv.lock` (§3). [PR-D3/D4]

## 12. Duas famílias de métricas (proibido misturar)

- **`reader_metrics`** — mede o LEITOR: CER/WER vs `surface`, cabeçalho (data_turno,
  vigilantes, unidade), `descricao` e `hora` por linha, FALSE_INCIDENT, recusa correta.
  **Só esta família entra no G1-S.**
- **`parser_ceiling`** — limitações estruturais do extractor line-based: `item`, `acao`
  e `resolvido` saem `missing` por construção (`table_rules._content_row` só preenche
  descricao/hora). Reportadas à parte, **excluídas** da comparação de leitores; baseline
  honesto para um futuro extractor de colunas.

Saída pública: `docs/eval_synthetic_summary.json` — **agregados apenas, sem valores de
campo** (passa no mesmo gate de PII sem exceção; `scan_text_for_pii` como segunda camada).
