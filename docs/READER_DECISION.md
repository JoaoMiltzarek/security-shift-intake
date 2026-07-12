# READER_DECISION — Critérios de seleção de leitor

> Documento **normativo** para a escolha de qualquer novo leitor.  
> Regra: critérios escritos e commitados **antes** de qualquer nova rodada de eval.  
> Origem: DATASET_CONTRACT §1 + F1 timebox da branch SSI-1003. Os resultados
> congelados mais recentes estão em `eval_g1s_calibration.json`; números de rodadas
> anteriores não substituem esse artefato.

## Hardware de referência

| Item | Valor |
|------|-------|
| GPU | NVIDIA GeForce GTX 1050 Ti |
| VRAM total | 4096 MiB |
| VRAM livre (idle) | ~3094 MiB |
| Compute Capability | 6.1 |
| SO | Windows 10 Pro 10.0.19045 |

## Critérios de segurança do release (necessários, todos)

1. **Funciona em Windows nativo** (sem WSL2, sem Docker) — `pip install` limpo.
2. **VRAM ≤ 3 GB para inferência unitária** (uma folha/imagem por vez, DPI ≤ 100).
3. **Operar a nível de linha ou página inteira** — leitores que exigem página inteira
   como única unidade são aceitos; leitores que só operam em palavra isolada têm
   alcance menor e devem demonstrar paridade de CER no bench-balanced.
4. **`false_incident_unreviewed=0`** — um incidente inventado pelo reader nunca pode
   chegar sem sinalização para revisão.
5. **`unsafe_clean=0`** — uma falha estrutural nunca pode virar saída limpa ou
   “sem alteração” aceita.
6. **`safe_review_recall=1.0`** — toda falha estrutural deve ser encaminhada para
   revisão.

Esses três invariantes são os gates executáveis de `make eval-safety`. O valor bruto
de `false_incident_count` continua publicado como ruído e carga de revisão do reader;
ele não é, sozinho, evidência de uma saída insegura.

## Critérios de candidate promotion (necessários, todos)

Um reader novo só substitui o **baseline fallback** se também cumprir:

1. **`false_incident_count=0`** em smoke/val — o candidato não pode aumentar a carga
   humana com ocorrências inventadas.
2. **`chars_to_type ≤ baseline fallback`** em bench-balanced/val — o candidato deve
   reduzir esforço humano, não aumentá-lo.
3. Todos os critérios de hardware e de segurança do release definidos acima.

O Tesseract atual é o **baseline fallback**, não um candidato que tenha passado a
barra de promoção. No artefato congelado de val ele tem `false_incident_count=4`;
portanto, não deve ser descrito como reader de qualidade aprovada. Ele permanece como
default apenas enquanto os gates de revisão segura forem comprovados e nenhum
candidato admissível superar sua carga de correção.

## Avaliações realizadas (branch SSI-1003, 2026-07-08)

### qwen2.5vl:3b (via Ollama) — LEITOR OPCIONAL (medido, não promovido)
- VRAM: ~3 GB → cabe na GPU (DPI 100, não 150 — OOM a 150 confirmado)
- Rodadas G-S2 históricas: smoke/val local_vlm CER=1.1343 vs local_ocr CER=0.9814.
- Artefato congelado atual: `chars_to_type=4902` vs baseline `3264` e
  `false_incident_count=9` vs baseline `4` — **pior que o Tesseract nas duas métricas
  de qualidade**.
- **Status: disponível via `INTAKE_VISION=local_vlm` (opt-in); NÃO é o default. O leitor
  default do v1 é Tesseract (`local_ocr`), conforme Makefile/factory/README.**

### qwen2.5vl:7b (via Ollama) — **VETADO**
- VRAM necessária: ~8 GB → 2× a VRAM disponível (4 GB)
- **Decisão: VETADO por hardware. Não puxar nem testar.**

### PaddleOCR-VL (VLM component — PP-ChatOCRv3) — **VETADO**
- Compute Capability mínima documentada: CC ≥ 7.0; GTX 1050 Ti = CC 6.1 → abaixo.
- Backends de serviço (vLLM, SGLang, FastDeploy) requerem Docker; sem Windows nativo.
- Pico de VRAM reportado: 40+ GB em A100 sem otimização; sem caminho INT4 documentado
  para Windows nativo.
- **Decisão: VETADO por CC < 7.0 + bloqueios Windows. Não instalar.**

### PP-OCRv5 (PaddleOCR clássico — sem VL) — CANDIDATO FUTURO
- `pip install paddleocr` nativo no Windows; VRAM < 1 GB; opera a nível de linha.
- Acurácia em handwriting: 80.1% (v5) vs 53% (v4) no conjunto oficial.
- **Não implementado nesta branch** (não estava no escopo F1; nenhuma pressão de
  rodada para justificar agora). Registrado aqui para retomada em branch futura.
- Critério de adoção: cumprir integralmente a seção **candidate promotion**, inclusive
  `false_incident_count=0` e `chars_to_type ≤ baseline fallback`, em bench-balanced/val.

### minicpm-v (via Ollama) — NÃO AVALIADO
- Tamanho: MiniCPM-V 2.5 (~3B) pode caber; MiniCPM-V 2.6 (8B) não cabe.
- Não pesquisado em detalhe nesta branch; tabelado como candidato futuro junto
  com PP-OCRv5 se G1-S mostrar necessidade.

## Decisão congelada para G1-S

O reader escolhido para o run de test foi **local_ocr** (Tesseract 5), como baseline
fallback. Em val, local_ocr teve menos `chars_to_type` (3264 vs 4902) e menos
`false_incident_count` (4 vs 9) do que qwen2.5vl:3b. Nenhum dos dois cumpriu a barra
atual de candidate promotion.

O run de test congelado foi reprovado pelo gate de parse tabular e continua publicado
como tal em `eval_g1s_calibration.json`. A escolha do baseline menos ruim não converte
esse resultado em aprovação de qualidade. Para qualquer nova troca de reader, os
critérios de **candidate promotion** acima devem ser definidos antes da rodada de val;
o split de test congelado não pode ser usado para retuning.
