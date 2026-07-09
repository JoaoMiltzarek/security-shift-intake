# READER_DECISION — Critérios de seleção de leitor (branch SSI-1003)

> Documento **normativo** para a escolha de qualquer novo leitor.  
> Regra: critérios escritos e commitados **antes** de qualquer nova rodada de eval.  
> Origem: DATASET_CONTRACT §1 + F1 timebox da branch SSI-1003.

## Hardware de referência

| Item | Valor |
|------|-------|
| GPU | NVIDIA GeForce GTX 1050 Ti |
| VRAM total | 4096 MiB |
| VRAM livre (idle) | ~3094 MiB |
| Compute Capability | 6.1 |
| SO | Windows 10 Pro 10.0.19045 |

## Critérios de admissão (necessários, todos)

1. **Funciona em Windows nativo** (sem WSL2, sem Docker) — `pip install` limpo.
2. **VRAM ≤ 3 GB para inferência unitária** (uma folha/imagem por vez, DPI ≤ 100).
3. **Operar a nível de linha ou página inteira** — leitores que exigem página inteira
   como única unidade são aceitos; leitores que só operam em palavra isolada têm
   alcance menor e devem demonstrar paridade de CER no bench-balanced.
4. **false_incident = 0 em smoke/val (G-S1 mantido)** — invariante de segurança.
5. **chars_to_type ≤ baseline** em bench-balanced/val — o leitor tem de reduzir
   esforço humano, não aumentar.

## Avaliações realizadas (branch SSI-1003, 2026-07-08)

### qwen2.5vl:3b (via Ollama) — LEITOR ATUAL
- VRAM: ~3 GB → cabe na GPU (DPI 100, não 150 — OOM a 150 confirmado)
- Rodadas G-S2: smoke/val local_vlm CER=1.1343 vs local_ocr CER=0.9814
- false_incident = 0 em ambas as rodadas → G-S1 mantido
- **Status: leitor em uso, já testado.**

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
- Critério de adoção: PP-OCRv5 `chars_to_type ≤ qwen2.5vl:3b` em bench-balanced/val.

### minicpm-v (via Ollama) — NÃO AVALIADO
- Tamanho: MiniCPM-V 2.5 (~3B) pode caber; MiniCPM-V 2.6 (8B) não cabe.
- Não pesquisado em detalhe nesta branch; tabelado como candidato futuro junto
  com PP-OCRv5 se G1-S mostrar necessidade.

## Regra de decisão para G1-S (leitor escolhido)

O leitor que entra no G1-S é **qwen2.5vl:3b** — único leitor VLM disponível e já
testado em smoke. O baseline é **local_ocr** (Tesseract 5 + lang=por).

Escolha final após val: o leitor com menor `chars_to_type` total E `false_incident=0`
entra no run de test. Em caso de empate técnico (diferença < 5%), local_ocr vence
por custo zero (sem servidor Ollama necessário).
