# Registro das fontes bundladas (PR-D1 — `docs/DATASET_CONTRACT.md` §3)

Todas sob **SIL Open Font License 1.1** (arquivo `<Fonte>.OFL.txt` ao lado de cada
`.ttf`), baixadas do repositório oficial `github.com/google/fonts` (diretório `ofl/`).
Cobertura de acentos PT-BR (ã á â ç é ê í õ ó ô ú, minúsculas e maiúsculas) **verificada
por código antes do commit** (método bitmap vs `.notdef`, o mesmo de
`tests/test_fonts_coverage.py`) + inspeção visual de amostra renderizada.

| Arquivo | Upstream (`ofl/<dir>`) | Atribuição | sha256 do `.ttf` commitado |
|---|---|---|---|
| `Caveat.ttf` (variable `[wght]`, renomeada de `Caveat[wght].ttf`) | `caveat` | Copyright 2014 The Caveat Project Authors (github.com/googlefonts/caveat) | `0bdb6b660482d31531b3945849fba5916b3ef8695da7024a9e6b9ee3c4157988` |
| `ShadowsIntoLight.ttf` | `shadowsintolight` | Copyright (c) 2010, Kimberly Geswein (kimberlygeswein.com) | `1347863151acdc00fa281daaba1a3543dbce5870b55f9cf7479a15bb84007681` |
| `JustMeAgainDownHere.ttf` | `justmeagaindownhere` | Copyright (c) 2010, Kimberly Geswein (kimberlygeswein.com) | `0412aa1e460666d339738991b48e9f4bd51e10b6f04e2e1341fce4d2b3244c31` |
| `PatrickHand-Regular.ttf` | `patrickhand` | Copyright (c) 2010-2012 Patrick Wagesreiter (mail@patrickwagesreiter.at) | `0f173b3e6cb6d1af25babf7f0057c5ac4ee11f9992b0469bb817e967ef4ad0fc` |
| `ReenieBeanie.ttf` | `reeniebeanie` | Copyright (c) 2010, James Grieshaber (james@typeco.com) | `0ea608aa325bf9e11c9590cc0b63dcf7cd215e270784f1ebbe6fad4927b31ff8` |

Notas:
- *Homemade Apple* foi descartada: está sob Apache 2.0 (diretório `apache/`), fora do
  critério OFL do contrato. *Reenie Beanie* entrou no lugar.
- Renomear o arquivo não modifica a fonte (as restrições de Reserved Font Name da OFL
  aplicam-se a fontes **derivadas**, não ao nome do arquivo em disco).
- Fonte nova só entra com: OFL.txt ao lado + linha nesta tabela + aprovação em
  `tests/test_fonts_coverage.py`.
