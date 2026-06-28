# Plano-mestre v2.0 — de beta honesto a fenômeno de respeito

> Documento estratégico para `security-shift-intake`. Escrito em 2026-06-28.
> Une (1) diagnóstico do que trava o projeto, (2) a virada técnica para torná-lo
> *funcional de verdade*, (3) a ciência (universidades + projetos reais) que sustenta
> cada decisão e (4) a estratégia para virar fenômeno no GitHub.
>
> Princípio herdado do próprio projeto: **nenhum número aqui é inventado.** Os números de
> terceiros estão atribuídos à fonte; os números *do seu projeto* só valem quando o seu
> `make eval` os produzir nas suas folhas.

---

## 0. TL;DR (a tese em um parágrafo)

O `security-shift-intake` **já é** um projeto de engenharia de respeito: pipeline tipado,
~370 testes mockados a custo zero, CI verde, gate de aprovação humana, guarda de privacidade,
métricas reproduzíveis, dois caminhos por config. O que falta para ele ser *funcional de
verdade* não é mais engenharia — é **um leitor melhor**. Hoje o Tesseract não lê cursivo
português, então quase tudo cai em revisão humana e o sistema "degrada com honestidade" mas
ainda **economiza pouco trabalho**. A virada da v2.0 é uma só: **trocar o leitor por um VLM
aberto rodando local** (atrás da interface `VisionClient` que você já construiu para isso),
medir contra um **benchmark real de manuscrito brasileiro (BRESSAY, ICDAR 2024)** e deixar a
revisão humana cair de "tudo" para "só o duvidoso". Isso preserva **todos** os seus invariantes
(local, sem API paga, PII nunca sai da máquina) e transforma o gate de "muleta" em
*human-in-the-loop calibrado* — exatamente o que a literatura de **learning to defer** (MIT)
mostra ser o ótimo. Com isso medido e um README que prova valor em 30 segundos, o projeto deixa
de ser portfólio e vira ferramenta que outras pessoas instalam.

---

## 1. Diagnóstico honesto — onde está o gargalo

### 1.1 O que já está de respeito (não mexer)

Estes pontos colocam o projeto acima de 95% dos repositórios de "document AI" no GitHub. Eles são
a sua vantagem — preserve-os religiosamente:

- **Arquitetura tipada e auditável.** Pipeline de estágios determinísticos com `PipelineState`
  em Pydantic; sem agentes mágicos, sem fluxo escondido. Cada estágio faz a coisa mais simples
  que funciona.
- **Camada anti-corrupção** (`RawDocumentExtraction` ↔ `NormalizedIncidentModel`). O domínio é
  desacoplado do layout da folha. Isso é design de gente sênior.
- **Gate humano que é máquina de estados de verdade**, com audit log imutável — não um botão de UI.
- **Honestidade radical**: OCR Quality Gate que entra em "safe mode" quando não consegue ler,
  caveats escritos no README, "nenhuma métrica fabricada", dados reais só em `private/`.
- **Provider abstraction** (`VisionClient`/`LLMClient`) mockada em todos os testes. **Esta é a
  porta por onde a v2.0 entra sem reescrever nada.**

### 1.2 O gargalo, dito sem rodeio

> O valor do produto é limitado por **uma** coisa: a fidelidade de leitura do manuscrito.

A sua própria auditoria já provou isto, com método, e está documentada honestamente:

- A reforma para o caminho de tabela levou erros **BLOCKER de 2 → 0** (`AUDITORIA_FOLHAS_REAIS.md`).
  Ótimo — o sistema parou de **inventar**. Mas...
- **Capturadas fielmente (CER ≤ 0.5): 0.** Ou seja: o sistema é *seguro*, mas ainda **não lê**.
  Tudo de conteúdo vira `must_review` e volta para o humano digitar.
- A Fase 4 mediu que pré-processamento (grayscale/Otsu/PSM 3/4/6) **não melhora** cursivo, e que o
  único ganho foi DPI 250→150. Conclusão sua, correta: **"o teto de fidelidade no custo-zero é o
  próprio Tesseract; subir exige um leitor melhor (VLM)."**

Tradução de produto: hoje o app **não reduz a carga de transcrição** — ele organiza, valida e
protege, mas o humano ainda redigita quase tudo. Para o usuário operacional (o vigia / o
supervisor), a economia de tempo real ainda é pequena. Esse é o degrau entre "beta honesto" e
"ferramenta que eu uso todo dia".

### 1.3 A boa notícia

Você **já antecipou a solução** e a registrou no `ROADMAP.md` ("Local open VLM behind the existing
`VisionClient`"). A v2.0 não é uma virada de mesa — é **executar o item nº 1 do seu próprio
roadmap**, agora que (a) os modelos abertos amadureceram muito em 2025 e (b) existe um benchmark
brasileiro para provar o ganho. O resto deste documento é o "como", com a ciência junto.

---

## 2. A virada técnica — trocar o leitor (sem quebrar um invariante sequer)

### 2.1 A ideia central

Tesseract sai do caminho crítico e entra um **VLM aberto rodando 100% local** como
`VisionClient`. Como tudo já passa por essa interface e é mockado nos testes, **o pipeline, o
schema, o gate e a UI não mudam**. Você implementa **um arquivo** (`src/clients/local_vlm.py`),
liga por config, e mede. Isso respeita, ponto a ponto:

| Invariante do projeto | Continua valendo? | Como |
|---|---|---|
| Sem API paga | ✅ | Modelo aberto, pesos locais (Ollama/vLLM/llama.cpp) |
| PII nunca sai da máquina | ✅ | Inferência on-device; nada de rede |
| Offline | ✅ | Pesos baixados uma vez; roda sem internet |
| Config-driven | ✅ | Novo client selecionado por env var, igual hoje |
| Mock em todos os testes | ✅ | O client real fica atrás do mesmo protocolo mockado |
| OCR honesto / human gate | ✅ **e melhora** | O VLM também devolve confiança; o que ele não lê continua indo para revisão — só que agora é **muito menos** |

> Em outras palavras: a v2.0 é uma **troca de motor**, não uma reforma. A engenharia que você
> fez (a abstração, os mocks, o gate) é exatamente o que torna essa troca barata. Esse é o
> retorno do investimento em design limpo.

### 2.2 Por que isso funciona (a evidência)

A literatura de 2025 é clara: **VLMs/LLMs multimodais leem manuscrito moderno com CER < 5%** —
uma ordem de grandeza melhor que o Tesseract em cursivo. Um estudo de *benchmarking* de HTR
publicado no *Journal of Documentation* (2025) reporta, por exemplo, **GPT-4o-mini com 1.71% CER
no IAM** e modelos LLM **superando o Transkribus** em manuscrito moderno. ([arXiv:2503.15195](https://arxiv.org/pdf/2503.15195),
[Emerald/Journal of Documentation](https://www.emerald.com/jd/article/81/7/334/1275080/Benchmarking-large-language-models-for-handwritten))

E o melhor: **não precisa ser modelo proprietário.** A onda de OCR aberto de 2025 alcançou (ou
superou) os serviços de nuvem, com modelos pequenos o bastante para rodar local. Isso é o que
torna a sua restrição "sem API paga" uma **vantagem de posicionamento**, não uma limitação.

### 2.3 Os candidatos a `VisionClient` (todos abertos e locais)

Recomendo avaliar nesta ordem (do mais "plug-and-play" ao mais "ajustável"):

1. **olmOCR-2-7B** (Allen Institute for AI / AI2) — *fine-tune* do **Qwen2.5-VL-7B** especializado
   em digitalizar PDFs/scans preservando layout, tabelas e **manuscrito**; treinado com RL (GRPO),
   pontua 82.4 no olmOCR-bench. Aberto, roda local. ([GitHub allenai/olmocr](https://github.com/allenai/olmocr))
2. **PaddleOCR-VL-0.9B** (Baidu) — VLM de *document parsing* **leve** (0.9B parâmetros) que reporta
   **96.3% no OmniDocBench v1.6** e lidera em texto/fórmula/tabela; suporta 109 idiomas (script
   latino, serve português). Cabe em hardware modesto. ([HF PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL),
   [GitHub PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR))
3. **Qwen2.5-VL-7B** (Alibaba) — o "all-rounder" de 2025: roda em **Ollama** (`ollama pull
   qwen2.5vl:7b`, ~6 GB, GPU de 12 GB em 4-bit) ou vLLM; forte em OCR multilíngue, tabelas e JSON
   estruturado. Base de quase todos os OCR-VLM acima. ([Qwen2.5-VL Technical Report](https://arxiv.org/pdf/2502.13923),
   [tutorial local](https://www.datacamp.com/tutorial/use-qwen2-5-vl-locally)) Há também o **Qwen3-VL**
   mais novo ([arXiv:2511.21631](https://arxiv.org/pdf/2511.21631)) para quando quiser subir mais.
4. **dots.ocr-3B** — alternativa intermediária de bom custo-benefício mencionada nos comparativos
   abertos de 2025.

> Prova de que o caminho é real: já existem projetos no GitHub fazendo exatamente "OCR local com
> VLM, sem nuvem, sem custo" — p.ex. [`ahnafnafee/local-llm-pdf-ocr`](https://github.com/ahnafnafee/local-llm-pdf-ocr)
> (usa olmOCR) e [`ceodaniyal/local-llm-ocr-ollama`](https://github.com/ceodaniyal/local-llm-ocr-ollama).
> Isso valida a demanda **e** te dá um padrão competitivo para superar (eles não têm o seu gate
> humano, sua auditoria nem sua honestidade de eval — esse é o seu fosso).

### 2.4 A tabela é uma sub-tarefa específica — trate-a à parte

A folha "Controle de ocorrências" é uma **tabela de N linhas**, não texto corrido. Leitura de
*célula* é um problema próprio. Duas opções, ambas locais:

- **PP-StructureV3** (PaddleOCR 3.0) faz *layout analysis + table recognition* ponta a ponta e
  exporta Markdown; o relatório técnico afirma casar a precisão de VLMs de bilhões de parâmetros a
  uma fração do custo computacional. ([PaddleOCR 3.0 Technical Report — arXiv:2507.05595](https://arxiv.org/pdf/2507.05595),
  [docs PP-StructureV3](https://paddlepaddle.github.io/PaddleX/3.5/en/pipeline_usage/tutorials/ocr_pipelines/PP-StructureV3.html))
- **Table Transformer (TATR)** / abordagens de *table structure recognition* com DETR para
  segmentar células de forma robusta, em vez da heurística de linhas atual.

Estratégia recomendada: **detectar a estrutura da tabela** (PP-Structure) → **ler cada célula com
o VLM** → preencher o seu `RawDocumentExtraction`. O seu `table_rules.py` vira o *fallback*
determinístico, não o leitor principal.

### 2.5 O que NÃO muda (e é o motivo de o usuário confiar)

A confiança baixa continua bloqueando; o humano continua sendo o dono do "enviar". A diferença é
de **proporção**: hoje 100% vai para revisão; com um leitor de CER < 5%, a maior parte chega
**pré-preenchida e correta**, e o humano só confirma/corrige o resto. É aí que nasce a economia de
tempo — e é exatamente o desenho de *learning to defer* (§3.2).

---

## 3. A ciência por trás (universidades + pesquisa real)

Esta seção é o que faz o projeto virar "de respeito" também **academicamente**: cada decisão tem
literatura por trás. Use estas referências no README e na seção de design — elas elevam o repo de
"app legal" para "implementação informada por pesquisa".

### 3.1 Reconhecimento de manuscrito (HTR) — o estado da arte mudou

- **Benchmarking de LLMs para HTR** (2025, *Journal of Documentation* / [arXiv:2503.15195](https://arxiv.org/pdf/2503.15195)):
  MLLMs atingem **CER < 5%** em manuscrito moderno e **superam o Transkribus**; também mostram a
  fraqueza honesta — pior desempenho fora do inglês e pouca autocorreção. Isso te dá tanto a
  justificativa para trocar de leitor **quanto** o caveat para escrever no README (português é mais
  difícil que inglês → meça, não presuma).
- **BRESSAY** — *A Brazilian Portuguese Dataset for Offline Handwritten Text Recognition*
  (**ICDAR 2024**). **Esta é a peça que falta no seu projeto.** 1.000 páginas, 1.000 escritores,
  30.090 linhas, ~416 mil palavras, com **exatamente os seus desafios**: texto ilegível, **riscado**,
  rasuras, *overwriting*, manchas. É o **benchmark real** que substitui a dependência só do seu
  Tier B sintético (que você mesmo marcou como "limite otimista"). Disponível em GitHub.
  ([Springer/ICDAR 2024](https://link.springer.com/chapter/10.1007/978-3-031-70536-6_19),
  [competição BRESSAY](https://link.springer.com/chapter/10.1007/978-3-031-70552-6_21),
  [TC-11 dataset](https://tc11.cvc.uab.es/datasets/BRESSAY_1))
  → Com BRESSAY você passa a reportar **CER/WER em manuscrito brasileiro real**, com baseline
  (Tesseract) vs. o novo VLM. É a métrica-manchete que hoje está "pending".

### 3.2 Human-in-the-loop não é gambiarra — é teoria ótima (MIT)

O seu gate "OCR ruim → defere ao humano" tem nome e teoria: **Learning to Defer**.

- **Mozannar & Sontag (MIT), *Consistent Estimators for Learning to Defer to an Expert*, ICML 2020**
  ([arXiv:2006.01862](https://arxiv.org/pdf/2006.01862)): formaliza um sistema que **ou prediz, ou
  defere a decisão a um especialista**, aprendendo conjuntamente o classificador e o "rejeitador"
  com custos específicos do domínio. É **a** referência do seu desenho.
- Linha seguinte: *Human-AI Collaboration in Decision-Making: Beyond Learning to Defer*
  ([arXiv:2206.13202](https://ar5iv.labs.arxiv.org/html/2206.13202)) e a tese de PhD do Mozannar
  (*Training Human-AI Teams*, MIT 2024).

A consequência prática para a v2.0 é linda: **quanto melhor o leitor, menor a taxa de deferência,
maior a economia de trabalho humano — sem nunca abrir mão da segurança.** Você pode até reportar a
"taxa de deferência" como KPI (% que precisou de humano) e mostrá-la caindo do v1 para o v2. Isso é
ouro de narrativa.

### 3.3 A curadoria é um ciclo de aprendizado ativo (selective prediction + active learning)

A sua etapa de `curadoria/*.json` (`draft_by_claude` → `verified_by_user`) **já é** o começo de um
*active learning loop*. A pesquisa conecta isso:

- **ASPEST — *Bridging the Gap Between Active Learning and Selective Prediction*** (TMLR 2024,
  [arXiv:2304.03870](https://arxiv.org/html/2304.03870)): combinar *selective prediction* (deixar o
  modelo se abster) com *active learning* (pedir rótulo humano nos casos mais informativos) usa o
  trabalho humano de forma muito mais eficiente. É o nome técnico do seu loop de curadoria.
- **Calibração de confiança**: a literatura de extração em produção mostra que *confidence scores*
  brutos calibram mal; vale calibrar (pseudo-acurácia / binning) para que o limiar de revisão seja
  honesto. Isso transforma o seu "confidence < threshold → must_review" de heurística em métrica
  calibrada (já está no seu roadmap como "confidence calibration").

### 3.4 Por que "staged pipeline" é a arquitetura certa (Berkeley)

Você defende, com razão, que isto **não** é "multi-agente". A academia te dá a linguagem:

- **BAIR / Berkeley — *The Shift from Models to Compound AI Systems*** (Zaharia et al., fev/2024,
  [BAIR blog](https://bair.berkeley.edu/blog/2024/02/18/compound-ai-systems/)): os melhores
  resultados vêm de **sistemas compostos de múltiplos componentes especializados** (modelos,
  *retrievers*, ferramentas, modelos menores) orquestrados — não de um modelo monolítico. O seu
  pipeline é um **compound AI system** textbook: VLM-leitor + regras de tabela + classificador +
  roteamento determinístico + gate humano. Use esse termo — ele é preciso e está na moda pelos
  motivos certos.

> Resumo da seção: você não precisa inventar nada. Precisa **nomear** o que já fez com os termos da
> literatura (compound AI system, learning to defer, selective prediction/active learning) e
> **medir** com um dataset real (BRESSAY). Isso é o que separa "projeto de fim de semana" de
> "projeto que um pesquisador respeita".

---

## 4. Roadmap v2.0 — fases pequenas, verificáveis (no seu próprio estilo)

Cada fase tem uma **Definition of Done** que só conta quando o comando roda e produz a saída — igual
ao seu `PROJECT_SPEC.md`. Mantém o hábito de **commit por micro-etapa**.

### Fase 1 — O leitor VLM local (a virada)
- **O quê:** `src/clients/local_vlm.py` implementando `VisionClient` contra um endpoint local
  (Ollama/vLLM, OpenAI-compatible). Seleção por env var (`INTAKE_VISION=local_vlm`), igual ao
  resto. Mock correspondente nos testes.
- **DoD:** `make demo-pipeline FILE=...` roda a folha real pelo VLM local, **offline**, e imprime a
  transcrição; testes mockados verdes; `make privacy-check` verde; zero chamada de rede.

### Fase 2 — Benchmark de verdade (BRESSAY) — preenche o "pending"
- **O quê:** baixar BRESSAY; `evals/eval_htr_bressay.py` calculando **CER/WER** do **Tesseract
  (baseline)** vs. **VLM local** num *split* held-out.
- **DoD:** `make eval` escreve no `EVAL_REPORT.md` uma tabela real "Tesseract vs VLM" em manuscrito
  brasileiro, com o caveat de domínio (redação ≠ formulário). **Nenhum número digitado à mão.**
  Esta é a métrica-manchete que hoje está "pending".

### Fase 3 — Estrutura de tabela robusta
- **O quê:** PP-StructureV3 (ou TATR) para segmentar células da folha de ocorrências; VLM lê cada
  célula; `table_rules.py` vira *fallback*. Sem alargar a detecção (não quebrar a folha "S/A").
- **DoD:** na sua folha real curada, as N linhas (Item/Hora/Descrição/Ação/Resolvido) são extraídas
  por célula; teste de não-regressão da folha "S/A" continua verde.

### Fase 4 — Deferência calibrada (o KPI que vende)
- **O quê:** calibrar confiança; reportar **taxa de deferência** (% que foi para humano) e
  **recall de erro do crítico** (dos que tinham erro, quantos foram flagados). Conectar a curadoria
  como *active learning loop* (ASPEST).
- **DoD:** `EVAL_REPORT.md` mostra taxa de deferência caindo v1→v2 e recall de erro ≥ alvo; curva de
  confiabilidade (accuracy × confidence) gerada por código.

### Fase 5 — Generalização (de "folha de segurança" para "qualquer formulário manuscrito")
- **O quê:** é a expansão de mercado. O seu sistema **já é config-driven**; prove isso publicando
  **um segundo tipo de formulário** (p.ex. ficha de manutenção, registro de portaria, planilha de
  ronda) como **só um novo YAML + template**, sem mudar código.
- **DoD:** `configs/<novo_formulario>.yaml` roda ponta a ponta com a mesma base de código; README
  mostra "adicionar um formulário = escrever um YAML".
- **Por que importa:** isto multiplica o público do repo. "Intake de folha de vigilância" tem N
  usuários; "**pipeline local, privacy-first, para digitalizar qualquer formulário manuscrito com
  revisão humana**" tem 1000×N.

### Fase 6 — Empacotamento (instalar tem que ser trivial)
- **O quê:** instalador/compose que traz o runtime do VLM + idioma; `make setup` único; talvez
  imagem Docker (CPU e GPU). Fechar o roadmap antigo ("one-command installer").
- **DoD:** uma pessoa sem o seu ambiente roda o demo em < 10 min seguindo o README.

> Sequência inegociável: **Fase 1 → 2 primeiro.** Só "trocar o leitor" sem medir não convence
> ninguém; o par leitor-novo + número-real-no-BRESSAY é o que vira a chave de "beta" para
> "funciona, e aqui está a prova".

---

## 5. Virar fenômeno no GitHub — estratégia concreta

A pesquisa sobre repositórios que explodem é unânime num ponto: **"se a pessoa não entende o que o
projeto faz e não vê que funciona em ~30 segundos, ela fecha a aba."** Um repo com 12 estrelas e um
README pensado vence um repo com 200 estrelas de um tweet viral e README vazio.
([daytona.io](https://www.daytona.io/dotfiles/how-to-write-4000-stars-github-readme-for-your-project),
[awesome-readme](https://github.com/matiassingers/awesome-readme))

### 5.1 Posicionamento (a frase que vende)

Pare de chamar de "security shift intake" no primeiro contato. O *hook* é:

> **"Digitalize formulários manuscritos com IA — 100% local, sem nuvem, sem inventar dado. O humano
> aprova; a máquina nunca envia sozinha."**

Esse posicionamento ataca uma dor real e enorme (digitalizar papel manuscrito) e crava **três
diferenciais que quase nenhum concorrente tem juntos**: *local/privado*, *anti-alucinação*,
*human-in-the-loop auditável*. Num mercado lotado de "cole seu doc na nossa API na nuvem", **ser o
contrário disso é a marca**.

### 5.2 README que prova valor em 30 segundos

Ordem recomendada (respeitando o "tempo do leitor"):
1. **Uma frase + um GIF.** O GIF mostra: folha manuscrita entra → campos preenchidos aparecem →
   humano corrige um campo → mensagem copy-ready sai. Um GIF de 15s vale mais que 2 páginas.
2. **Badges** (CI, license, Python) — você já tem.
3. **Quickstart de 3 linhas** que roda o demo sintético **sem arquivo e sem API** (o seu
   `make demo-pipeline-mock` já é perfeito para isso — destaque-o no topo).
4. **A tabela de resultados reais** (depois da Fase 2): "CER em manuscrito BR: Tesseract X% → VLM
   local Y%". Número honesto, reproduzível, com baseline. **Isto é o que dá credibilidade.**
5. **Os diferenciais** (local, anti-alucinação, gate humano) em três bullets.
6. **Arquitetura em 10 segundos** (você já tem) + link para os docs.

### 5.3 A honestidade como marketing

A sua maior vantagem competitiva é cultural: o repo **não mente**. "OCR é best-effort, aprovação
humana é obrigatória, automação insegura é bloqueada." Em 2026, num mar de demos infladas, **um
projeto que documenta os próprios limites com método** gera confiança — e confiança é o que vira
estrela, fork e contribuição. Escreva um post curto ("Por que recusei API paga e construí um doc-AI
que admite quando não consegue ler") — esse é o tipo de conteúdo que vai para o topo do Hacker News
e do r/MachineLearning.

### 5.4 Comunidade (a mecânica de crescimento)

- **`CONTRIBUTING.md` + `CODE_OF_CONDUCT.md` + 10–15 issues `good first issue`** bem escritas
  (cada uma: contexto, arquivo, critério de aceite). Projetos crescem quando estranhos conseguem
  contribuir em uma tarde.
- **Issues "help wanted" temáticas**: "adicione um `VisionClient` para o modelo X", "adicione um
  YAML para o formulário Y", "melhore a leitura da coluna Hora". Você desenhou o sistema para ser
  extensível — **transforme cada ponto de extensão numa issue convidativa**.
- **Template de novo formulário** + um guia "como adaptar para o seu formulário" — converte
  curiosos em usuários (e usuários em divulgadores).
- **Demo público** (mesmo que rodando só o caminho sintético/mock numa página) para quem não quer
  instalar nada.

### 5.5 Lançamento

Quando Fases 1–2 estiverem prontas (leitor novo + número real):
- **Show HN** + **r/MachineLearning** ("[P]") + **r/selfhosted** (adora "local, sem nuvem") +
  **r/brdev** (é brasileiro, manuscrito BR, comunidade local engaja).
- Título que lidera com o diferencial: *"Local, privacy-first handwriting-to-spreadsheet pipeline
  that refuses to hallucinate (and tells you when it can't read)."*
- Leve **o número e o GIF** no primeiro comentário. Resultado reproduzível + demo honesta = a
  combinação que a pesquisa de virabilidade aponta.

---

## 6. Riscos e o que NÃO fazer

- **Não quebre os invariantes para ganhar acurácia.** Se um dia oferecer VLM em nuvem, que seja
  **opt-in explícito**, nunca default, nunca com PII real sem consentimento — exatamente como o seu
  `ROADMAP.md` já diz. A identidade do projeto *é* o local-first.
- **Não troque a honestidade por hype.** Não escreva "99% de acurácia" — escreva o número que o
  `make eval` produziu, com o caveat de domínio (BRESSAY é redação escolar; folha de ocorrência tem
  outro vocabulário e layout — meça nas suas folhas também).
- **Não alargue a detecção de tabela** a ponto de quebrar a folha "S/A" (você já mediu isso; é uma
  regressão conhecida).
- **Custo de hardware é real.** VLM 7B quer ~8–12 GB de VRAM; documente um caminho **CPU/modelo
  menor** (PaddleOCR-VL-0.9B) para quem não tem GPU. Isso amplia o público.
- **Não deixe o `curadoria` parado.** Sem `verified_by_user`, não há ground-truth — e sem
  ground-truth, a Fase 4 não fecha. É barato e destrava as métricas.

---

## 7. Próximos passos concretos (o que dá para fazer já)

1. **Decidir o leitor da Fase 1** (sugestão: começar por **Qwen2.5-VL-7B via Ollama** pela
   facilidade, com **PaddleOCR-VL-0.9B** como plano B para CPU).
2. **Eu implemento a Fase 1** com você: o `src/clients/local_vlm.py` + mock + teste +
   seleção por env var, no padrão do projeto (commit por micro-etapa, `make check` verde). A
   inferência roda na sua máquina (Ollama), mas todo o *scaffolding* eu escrevo aqui.
3. **Baixar BRESSAY** e montar o `eval_htr_bressay.py` (Fase 2) para gerar o primeiro número real.
4. **Reescrever o topo do README** com o posicionamento de §5.1 + espaço para o GIF e a tabela de
   resultados.

Diga qual leitor você quer começar e se quer que eu já escreva o `local_vlm.py` + o harness do
BRESSAY — dá para deixar o esqueleto pronto agora, no estilo do repo.

---

## 8. Fontes

**HTR / OCR — estado da arte e modelos**
- Benchmarking LLMs for Handwritten Text Recognition (2025): https://arxiv.org/pdf/2503.15195 · https://www.emerald.com/jd/article/81/7/334/1275080/Benchmarking-large-language-models-for-handwritten
- Qwen2.5-VL Technical Report: https://arxiv.org/pdf/2502.13923 · Qwen3-VL: https://arxiv.org/pdf/2511.21631
- olmOCR (AI2): https://github.com/allenai/olmocr
- PaddleOCR-VL (HF): https://huggingface.co/PaddlePaddle/PaddleOCR-VL · PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- PaddleOCR 3.0 / PP-StructureV3: https://arxiv.org/pdf/2507.05595 · https://paddlepaddle.github.io/PaddleX/3.5/en/pipeline_usage/tutorials/ocr_pipelines/PP-StructureV3.html
- Rodar VLM local (Ollama/vLLM): https://www.datacamp.com/tutorial/use-qwen2-5-vl-locally
- Projetos GitHub de OCR local com VLM: https://github.com/ahnafnafee/local-llm-pdf-ocr · https://github.com/ceodaniyal/local-llm-ocr-ollama

**Dataset brasileiro (a peça que falta)**
- BRESSAY (ICDAR 2024): https://link.springer.com/chapter/10.1007/978-3-031-70536-6_19 · competição: https://link.springer.com/chapter/10.1007/978-3-031-70552-6_21 · dataset: https://tc11.cvc.uab.es/datasets/BRESSAY_1

**Human-in-the-loop / ciência do design**
- Learning to Defer (Mozannar & Sontag, MIT, ICML 2020): https://arxiv.org/pdf/2006.01862
- Beyond Learning to Defer: https://ar5iv.labs.arxiv.org/html/2206.13202
- ASPEST (active learning + selective prediction, TMLR 2024): https://arxiv.org/html/2304.03870
- Compound AI Systems (BAIR/Berkeley, Zaharia et al., 2024): https://bair.berkeley.edu/blog/2024/02/18/compound-ai-systems/

**Estratégia open-source / README**
- How to write a 4000-stars README: https://www.daytona.io/dotfiles/how-to-write-4000-stars-github-readme-for-your-project
- awesome-readme: https://github.com/matiassingers/awesome-readme
- 12 ways to get more GitHub stars: https://blog.tooljet.com/12-ways-to-get-more-github-stars-for-your-open-source-projects/
