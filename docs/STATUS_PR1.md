# STATUS — PR-1 "Medição primeiro" (branch `SSI-1002-hardening`)

> **Propósito deste arquivo:** registro de retomada entre sessões. Diz em que ponto o
> plano da PR-1 está, o que foi feito (com commit) e o que falta. Atualize-o ao final
> de cada sessão de trabalho nesta PR. O contrato normativo das métricas é
> [`EVAL_PROTOCOL.md`](EVAL_PROTOCOL.md); a escada de PRs e os gates estão em
> [`ROADMAP.md`](ROADMAP.md).

## A pergunta que a PR-1 responde

**O VLM local reduz esforço humano em folha real?** A PR-1 não muda o orquestrador:
ela constrói a régua (eval instrumentado + probes + contrato congelado) que decide as
PRs seguintes (PR-2 escalonamento / PR-2b reparo / PR-3 calibração) pelos gates G1–G3.

## Feito (com commit)

| # | Item do plano | Commit |
|---|---|---|
| 1a.1 | `docs/EVAL_PROTOCOL.md` (fórmulas, gates G1–G3, mínimos, whitelist, failure matrix) | `76eaf52` |
| 1a.2 | `TranscriptionResult.confidence_source` honesto nos 3 clientes + estado do pipeline | `87a619d` |
| 1b.3-5 | Eval real instrumentado: `--vision/--dpi/--n`, metadados forenses, métricas §2 (`parse_table_success`, esforço, probe repairability), captura de `RuntimeError`, comparação pareada `--compare`, público por whitelist + testes da failure matrix | `953e706` |
| 1b.6 | `tests/test_vlm_contract.py` — contrato VLM→tabela congelado (S/A, ocorrência, `[ilegível]`, caixa, markdown) | `b473e1f` |
| 1b.7 | `scripts/build_bressay_manifest.py` + teste + `EVAL_BRESSAY.md` atualizado (papel rebaixado a sanity check) | `7082e1a` + docs |
| 1b.8 | Makefile `eval-real` (VISION/DPI/REAL_N) | `b015951` |
| 1b.8 | README: demo de 3 minutos honesta + protocolo de medição | commit docs |
| 1b.8 | ROADMAP: escada de PRs + gates numéricos + SLO pendente | commit docs |
| extra | **Bug real achado pela régua:** Ollama 0.31.1 devolve HTTP 500 com `logprobs:true` + visão → retry único sem logprobs em `local_vlm.py` (`confidence_source` segue honesto) | commit fix |

`make check` verde (495+ testes, mockados, $0) e `make privacy-check` OK a cada commit.

## Rodadas reais já executadas nesta máquina (evidência em `docs/eval_real_summary.json`)

Todas **DIRECIONAIS** (0 folhas `verified_by_user`; 2/4 folhas com arquivo — as outras
2 são `pending_file`). Nenhum número abaixo é digitado à mão; tudo vem do JSON gerado.

| rodada | ran | parse_table_success | chars_to_type | qualidade | conf_source | s/folha |
|---|---|---|---|---|---|---|
| `local_ocr` DPI 150 (baseline) | 2/4 | 0/2 | 319 | low, low | tesseract | ~2.9 |
| `local_vlm` DPI 150 | 0/4 | — | — | — | — | — (**OOM**: página A4@150 estoura a VRAM; ver abaixo) |
| `local_vlm` DPI 100 | 2/4 | **2/2** | **122** | good, good | **logprobs** | ~177 |
| `local_vlm` DPI 72 | 2/4 | 1/2 | 338 | good, good | logprobs | ~151 |

Sensibilidade a DPI: 72 degrada (pior que o baseline em esforço), 100 é o ponto de
operação, 150 estoura a VRAM — a curva tem forma, não é ruído.

**Pareado (G1, baseline_dpi150 × vlm_dpi100):** `only_vlm 6 × only_baseline 0`
(margem 6 ≥ 2), taxa 2×0, esforço 122 < 319 → **todos os componentes numéricos do G1
a favor do VLM**; falta só o **SLO** (~177 s/folha é aceitável? decisão do usuário,
EVAL_PROTOCOL §5). `repairable_ratio` do VLM = 0.0 (não emite geometria) → o reparo
por bbox-crop (G2) não se aplica ao caminho VLM; se houver reparo na PR-2, é por
**região fixa ancorada no rótulo**. G3: pré-condição atendida (`logprobs` real), mas
**7 campos comparados < 50** → nenhuma decisão de threshold ainda.

**Aprendizados de hardware (medidos):** (1) Ollama 0.31.1 devolvia 500 com
`logprobs:true` em payload de visão no servidor frio — corrigido com retry sem
logprobs no cliente; com o modelo quente a DPI 100, logprobs reais voltam. (2) DPI 150
numa A4 pede buffer CUDA de ~8.6 GB no encoder de visão → OOM nesta GPU; **DPI 100 é o
ponto de operação do VLM neste hardware** (827×1169 cabe).

## Falta (em ordem de valor)

1. **Humano (a alavanca mais barata):**
   - Salvar as 2 fotos pendentes que a curadoria referencia (`pending_file`) em
     `private/reais/` — hoje só 2 de 4 folhas rodam.
   - Conferir as 4 curadorias → `review_status: verified_by_user`
     (`docs/CURADORIA_FORMATO.md`). Sem ≥10 verificadas, todo relatório é DIRECIONAL.
   - **Declarar o SLO** de `tempo_por_folha` em `EVAL_PROTOCOL.md` §5 — G1 não pode
     ser avaliado como "passou" sem ele.
   - Ampliar o conjunto curado (cada folha nova verificada vale mais que código).
2. **Sanity check BRESSAY (opcional, secundário):** baixar a release
   (`docs/EVAL_BRESSAY.md` §1), `python scripts/build_bressay_manifest.py --n 20`,
   `make eval-bressay N=20`.
3. **Fechar o G1 e decidir a PR-2**: os componentes numéricos já estão a favor do
   VLM (tabela acima), mas com n=2 e 0 verificadas a decisão é **provisória por
   construção** — verificar curadorias + declarar SLO transforma isso em decisão.
4. **Capturar transcrições reais do qwen** sobre a folha sintética de `samples/` e
   complementar as fixtures de `tests/test_vlm_contract.py` (nota no docstring).

## Fora do escopo da PR-1 (adiado com gate)

Escalonamento de página (PR-2, G1), reparo por recorte (PR-2b, G2), calibração (PR-3,
G3), summary dia/noite + `.xlsx` (trilha de produto, pós-prova), fine-tune HTR (M-E).
Motivos verificados no plano e na tabela do `ROADMAP.md`.

## Como retomar numa sessão nova

```bash
git log --oneline -15          # os commits da tabela acima
make check                     # deve estar verde antes de qualquer mudança
# rodadas (precisa Tesseract no PATH; VLM precisa de `ollama serve` + qwen2.5vl:3b):
make eval-real VISION=local_ocr DPI=150
make eval-real VISION=local_vlm DPI=100   # 150 estoura a VRAM desta GPU (medido)
PYTHONPATH=. uv run python -m evals.eval_extraction_real --compare \
  private/audit/eval_real_detailed_local_ocr_dpi150.json \
  private/audit/eval_real_detailed_local_vlm_dpi100.json
```
