# Handwriting fonts

**Bundladas desde a PR-D1** (mudança deliberada da política no-binary anterior,
registrada em `docs/DATASET_CONTRACT.md` §3): cinco fontes handwriting **SIL OFL 1.1**
vivem neste diretório, cada uma com seu `<Fonte>.OFL.txt` ao lado. Proveniência,
atribuição e sha256 de cada arquivo: [`FONTS.md`](FONTS.md). Cobertura dos acentos
PT-BR é garantida por `tests/test_fonts_coverage.py` — fonte nova só entra passando
nesse teste e ganhando linha no registro.

Se este diretório estiver vazio (ex.: checkout parcial), o renderer cai no fallback da
fonte default do Pillow — o pipeline segue rodando fim a fim, só que o output parece
digitado em vez de manuscrito (`data/generators/fonts.py`).

> **Honesty caveat (também no README principal):** "manuscrito" renderizado por fonte é
> *mais fácil* de ler que manuscrito humano real, então scores de transcrição/extração
> sobre folhas sintéticas são um **limite superior otimista** do desempenho real.
