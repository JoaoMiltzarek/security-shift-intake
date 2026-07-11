# for_codex.md — Diário de execução do plano de fechamento (F0–F11)

> **O que é isto:** registro extremamente detalhado da execução do plano "Fechamento entregável
> + showcase" por uma sessão de IA (Claude Code). Cada micro-step executado, comando rodado,
> saída real, decisão e desvio está documentado aqui, DENTRO do próprio commit do micro-step.
> **Se você é o Codex / uma nova sessão / um humano retomando:** leia `## ESTADO ATUAL` e siga
> o "RETOME AQUI". O plano completo aprovado está em
> `C:\Users\charu\.claude\plans\quero-alinhar-esse-projeto-steady-sonnet.md` (fora do repo);
> o `## MAPA DO PLANO` abaixo é o espelho executável dele.
> Convenções: branch por fase `SSI-10xx-<slug>`; commits `tipo(SSI-10xx): descrição` (PT,
> 3ª pessoa, autor JoaoMiltzarek, sem co-author); commit por micro-alteração; NUNCA fazer push
> (o usuário faz). `make` só no Git Bash. Tesseract: `PATH="$LOCALAPPDATA/Tesseract-OCR:$PATH"`.

---

## ESTADO ATUAL

- **Fase corrente:** F1 — Contratos vermelhos (SSI-1005)
- **Branch:** `SSI-1005-tri-state-estrutural` (criada de `SSI-1004-base-primeira-impressao@f399b7e9`;
  F0 completo — 8 commits, baseline 598 passed/1 skipped + privacy-check OK)
- **Último commit:** F0.5 (`chore(SSI-1004): registra baseline verde da fase F0`)
- **Micro-step corrente:** F0.6 — preparar corpo do PR da fase (push é do usuário)
- **RETOME AQUI:** F0 completo. Próxima fase: F1 — criar branch `SSI-1005-tri-state-estrutural`
  a partir desta branch (F1/F2 dependem do F-12 já aplicado aqui) e escrever os contratos
  vermelhos (ver MAPA F1.1–F1.5).
- **Bloqueios abertos:** nenhum.

---

## CONTEXTO ESSENCIAL (para retomada a frio)

**O produto:** pipeline local de intake de folhas de ocorrência de segurança (PDF/foto
manuscrita → OCR Tesseract → extração por regras → revisão humana em cockpit web (FastAPI +
htmx + SQLite) → planilha + mensagem copy-ready). Invariantes: aprovação humana obrigatória
antes de envio; dados sintéticos apenas no repo; nada de métrica fabricada; config em YAML.

**Por que este plano existe:** auditoria externa (Codex) achou 13 findings; os 2 release
blockers verificados em primeira mão:

1. **F-01 (colapso unknown→none):** `table_rules._table_region` retorna `[]` tanto para
   "header da tabela não encontrado" quanto para "tabela vazia"; `normalize.py:112` faz
   `no_occurrence = len(occurrences)==0`; `validate.py:172-178` transforma isso em campo
   "(sem alteração)" ACEITO com confiança 1.0. Resultado: falha de parse vira "sem ocorrência"
   válido e exportável — incidente real pode ser omitido silenciosamente. Agravante:
   `app.py:104-108` — editar um draft de zero linhas emite "(sem alteração)" com
   `source="human"` — lava a falha como confirmação humana.
2. **F-02 (aprovação não vinculada a revisão):** `repository.update_state` sobrescreve
   `state_json` sem tocar status; `ui_edit` edita até draft ENVIADO; `gate.send_draft` envia o
   state_json corrente sem re-validar → approve→edit→send envia conteúdo nunca aprovado.

**Solução (design aprovado):** tri-state `disposition: unknown|none|present` no
`NormalizedIncidentModel` (default seguro `unknown`; `none` só com evidência S/A explícita ou
confirmação humana; `unknown` → must_review → bloqueia tudo via `assert_reviewable` existente)
+ `Draft.revision`/`approved_revision`/`approved_state_sha256` (edit derruba aprovação; sent é
imutável; send re-valida) + cockpit com editor 0/1/N (radios de disposição + linhas
`occ__{i}__{col}` full-replace). Detalhes completos na seção MAPA DO PLANO e no plan file.

**Fatos de ambiente verificados nesta sessão (2026-07-11):**
- `make` OK no Git Bash (`ezwinports.make` via WinGet); `uv 0.11.23`; Python 3.11 em
  `%LOCALAPPDATA%\Programs\Python\Python311`; Tesseract em `%LOCALAPPDATA%\Tesseract-OCR`
  (fora do PATH — exportar antes de usar); `.venv` do repo funciona
  (`pytest --collect-only` = 599 testes).
- Hook "Fact-Forcing Gate" ativo: antes do 1º Bash da sessão e de cada Write/Edit novo,
  apresentar fatos no texto da resposta e repetir a chamada.
- `main@f359b129` ≡ SHA auditado `75bfc04` + progress.md (equivalência provada por git diff).

---

## LEDGER (cronológico — atualizar a cada micro-step)

### Sessão 2026-07-11 (Claude Code / Fable 5) — planejamento + início F0

- **[feito] Verificação da auditoria** (pré-execução, sem commits): 13/13 findings confirmados
  contra o HEAD com 8 agentes read-only + leitura direta. Refutados: "598 testes inflado"
  (599 coletados — honesto) e "sem testes de purge/privacy" (test_purge.py=8,
  test_privacy_check.py=18 existem). Fatos novos: `Makefile:10` já usa config tabular (F-12 é
  só script/API); `READER_DECISION.md:30` diz "qwen2.5vl:3b LEITOR ATUAL" (conflita com
  Tesseract default — corrigir em F0.4); test split congelado publica `false_incident_count: 1`;
  `eval_extraction_synthetic.py:56` hardcoda SUMMARY_PATH (F7 precisa de --output-dir).
- **[feito] Plano aprovado pelo usuário** com 3 diretrizes extras: enquadramento
  "trust engineering" honesto sobre cursiva; verification loop com Chromium real por fase;
  commits por micro-alteração ("bilhões"). + este arquivo for_codex.md.
- **[feito] F0.0** — branch `SSI-1004-base-primeira-impressao` criada de `main@f359b129`
  (worktree limpa confirmada por `git status --porcelain` vazio).
### Fechamento F0 (2026-07-11)
Commits da fase: `4d0f0eba` (for_codex), `259c6488` (rm progress.md), `6047dfef` (default
demo_pipeline), `b570614a` (default API), `020e3b52` (docstring loader), `a5ca2d99` (testes
config escalar explícita), `b1f0b621` (READER_DECISION), + fechamento F0.5.
Corpo de PR sugerido: "F0 (SSI-1004): base do release — remove progress.md quebrado, unifica o
default de config no produto tabular v1 (F-12: script/API/loader alinhados ao Makefile),
reconcilia a narrativa do reader (Tesseract default; qwen opcional medido) e registra baseline
verde (598 passed/1 skipped + privacy-check OK)."
Desvios do plano: nenhum. Nota: ruff auto-organizou imports dos 3 testes (incluído em F0.5).

- **[feito] F0.1** — for_codex.md criado e commitado (`4d0f0eba`).
- **[feito] F0.2** — `git rm progress.md`: arquivo era UTF-16/mojibake tracked na raiz (finding
  P-1 do scan de portfólio — "primeira coisa que um juiz vê"). Conteúdo era changelog stub sem
  valor; nada a preservar (os docs de status reais estão em docs/).

---

## MAPA DO PLANO (espelho executável — marcar [x] conforme conclui)

### F0 — Base + primeira impressão (SSI-1004, branch `SSI-1004-base-primeira-impressao`)
- [x] F0.1 criar for_codex.md + commit `docs(SSI-1004): cria diário de execução for_codex`
- [x] F0.2 `git rm progress.md` (mojibake na raiz) + commit `chore(SSI-1004): remove progress.md quebrado da raiz`
- [x] F0.3a `scripts/demo_pipeline.py:32` `DEFAULT_CONFIG` → `configs/controle_ocorrencias.yaml` + commit
- [x] F0.3b `src/api/app.py:146` `_DEFAULT_CONFIG` → `configs/controle_ocorrencias.yaml` + commit
- [x] F0.3c docstring `src/schema/loader.py` atualizada + commit
- [x] F0.3d ajustar 5 pontos de teste — feito: `test_app_config.py` invertido (default =
      controle_ocorrencias; override provado com htmicron); nos 4 fixtures, `_SCALAR_CONFIG =
      load_config(Path("configs/htmicron_security.yaml"))` passado a `create_app(config=...)`.
      `test_page_image.py` verificado config-agnóstico (só submit + GET imagem — sem mudança).
      SAÍDA REAL: `uv run pytest` nos 6 arquivos → **33 passed, 1 skipped** (skip pré-existente).
- [x] F0.4 `docs/READER_DECISION.md` reconciliado (qwen → "LEITOR OPCIONAL (medido, não
      promovido)"; default v1 = Tesseract). README verificado: já era consistente (qwen
      aparece só como opt-in INTAKE_VISION=local_vlm com números honestos) — sem mudança.
- [x] F0.5 baseline verde. SAÍDAS REAIS (2026-07-11):
      `make check` → ruff acusou 3 erros de import-order nos testes editados → `uv run ruff
      check --fix .` (3 fixed) → re-run: lint OK, mypy OK, **pytest: 598 passed, 1 skipped,
      84.61s**. `make privacy-check` → "privacy-check OK — no real data tracked, none outside
      private/, no PII in public files."
- [ ] F0.6 PR da fase (usuário faz push; corpo do PR no fechamento abaixo)

### F1 — Contratos vermelhos (SSI-1005, branch `SSI-1005-tri-state-estrutural`)
- [x] F1.1 feito: 2 xfail(strict) em test_table_rules — `test_missing_column_header_sets_
      tabela_nao_encontrada` e `test_found_but_empty_region_sets_tabela_encontrada` (ambos
      AttributeError hoje → xfail; strict força o flip em F2.A2).
- [x] F1.2 feito: `test_consecutive_content_rows_without_separator_merge` (documental,
      passa hoje). SAÍDA REAL: `pytest tests/test_table_rules.py -q` → **9 passed, 2 xfailed**.
- [x] F1.3 feito: 5 xfail(strict) em test_normalize — zero-rows→unknown, blank-rows→unknown,
      S/A→none, conteúdo→present, misto→present. SAÍDA REAL: **11 passed, 5 xfailed**.
- [ ] F1.4 `tests/test_local_ocr.py`: integração REAL — renderizar fixture 0/1/2 linhas
      (gerador `data/generators/templates/controle_ocorrencias.py`), Tesseract real, caminho de
      produção; 2 linhas nunca viram "sem alteração" aceito; skip limpo sem tesseract + commit
- [x] F1.5 feito: 2 xfail(strict) em test_api — `test_approve_edit_send_is_blocked` (send pós-
      edit retorna 200 + sender chamado hoje) e `test_edit_sent_draft_is_rejected` (edit de
      enviado retorna 200 hoje). SAÍDA REAL: **5 passed, 2 xfailed, 2.67s**.

### F2 — Tri-state estrutural (SSI-1005, mesma branch) — design A1..A6
- [ ] F2.A1 `src/schema/extraction.py`: `Disposition = Literal["unknown","none","present"]`;
      `NormalizedIncidentModel.disposition="unknown"`; `schema_version="1.1"`; validator
      before (JSON legado: present se tem occurrences, senão unknown) + validator after
      (`no_occurrence = disposition=="none"`). Testes novos test_schema_extraction + ajustar
      construtores em test_ocr_quality/_state, test_outputs/_norm, test_eval_extraction_real + commits (teste → impl)
- [ ] F2.A2 `table_rules.py`: `_table_region` → `None` quando `_COLHDR` não casa; `extract()`
      seta `RawDocumentExtraction.tabela_encontrada: bool` (novo campo, default True) + commits
- [ ] F2.A3 `normalize.py`: derivação tri-state (present > none-com-S/A > unknown); publicar
      `parse_times`/`parse_resolved` + flip do teste F1.3 + commits
- [ ] F2.A4 `validate.py` `validate_table`: 3 vias — unknown → ExtractedField "ocorrencias"
      conf 0.0 must_review com valor explicativo (distingue "tabela não encontrada" vs
      "nenhuma linha legível" via tabela_encontrada) + commits
- [ ] F2.A5 `ocr_quality.py:65-66`: relaxamento só p/ `disposition=="none"` + commits
- [ ] F2.A6 `outputs.py:38-39`: unknown → "(ocorrências não confirmadas)"; "Sem alteração" só p/ none + commits
- [ ] F2.V loop de verificação: `make demo-pipeline` Tesseract real numa fixture sem header →
      cockpit no browser mostra "(ocorrências não confirmadas)" + aprovação bloqueada; cenário
      `unknown_blocks_approve` no `scripts/browser_smoke.py` + commit; flip dos xfails F1.1/F1.4
- [ ] F2.PR fechamento de fase (make check + saída real aqui)

### F3 — Aprovação↔revisão (SSI-1006) — design B1..B3
- [ ] F3.B1 `src/api/models.py`: Draft += `revision:int=1`, `approved_revision:int|None`,
      `approved_state_sha256:str|None`; `src/api/db.py init_db` += ALTER TABLE idempotente via
      PRAGMA table_info + teste de migração (DB velho em tmp_path) + commits
- [ ] F3.B2 `repository.py`: `state_sha256()` (sha256 do STRING armazenado, nunca re-serializar);
      `update_state`: bloqueia sent (`DraftAlreadySentError`), revision++, APPROVED→PENDING +
      limpa approved_* + audit `approval_revoked`; audit `edited` com rev+sha12 (sem PII);
      `set_status(APPROVED)` estampa approved_revision+hash + commits (testes: bump, reset,
      sent-raise, stamp)
- [ ] F3.B3 `gate.send_draft`: re-roda `assert_reviewable(estado corrente)` + exige
      `approved_revision==revision` + hash igual; testes: approve→edit→send bloqueado +
      sender.call_count==0; hash-tamper bloqueado; legado approved_revision=None bloqueado + commits
- [ ] F3.ui `app.py ui_edit`: sent → HTTP 409 antes de qualquer trabalho + commit
- [ ] F3.V loop: browser — approve → edit → painel mostra rev N+1 + aprovação revogada; send
      bloqueado; cenário `approve_edit_send_blocked` no browser_smoke + flip xfail F1.5
- [ ] F3.PR fechamento de fase

### F4 — Cockpit 0/1/N (SSI-1007) — design C1..C3
- [ ] F4.C1 `_edit_table` reescrito: radios `disposicao` (`sem_alteracao`|`com_ocorrencias`,
      nenhum marcado se unknown); parsing `^occ__(\d+)__(item|hora|descricao|acao|resolvido)$`
      full-replace; linha em branco descartada; contradição → não persiste + re-renderiza com
      erro; "(sem alteração)" humano SÓ com confirmação explícita (fecha a lavagem
      app.py:104-108) + commits
- [ ] F4.C2 reclassificação: `classify(..., text=None)` compat; pós-edit texto canônico
      revisado → classify → route → build_outputs; reason menciona rev; `create_app(llm=)` + commits
- [ ] F4.C3 templates: `_review_body.html` grid 5 colunas + sobressalente + "Limpar linha"
      (`data-clear-row` em app.js); `_status_panel.html` mostra Revisão N/aprovada M + aviso
      legado; caminho escalar intocado (branch `normalized is not None`) + commits
- [ ] F4.V loop: browser — adicionar/limpar linha, contradição rejeitada; cenário
      `row_editor_0_1_N` no browser_smoke + commits
- [ ] F4.PR fechamento

### F5 — Auditoria rastreável (SSI-1008)
- [ ] F5.1 AuditEntry += revision + state_hash (detail sem PII) + testes + commits
- [ ] F5.2 snapshot por revisão (provar o que foi aprovado/enviado) + commits
- [ ] F5.3 "immutable" → "append-only pela aplicação" em models.py:36-37, README, docstrings + commit
- [ ] F5.PR fechamento

### F6 — Retenção + privacidade (SSI-1009)
- [ ] F6.1 `purge_demo_data.py:26` _DEMO_TARGETS += page_images, app.db-shm, debug + teste + commits
- [ ] F6.2 `privacy_check.py:50` _PUBLIC_TEXT_EXT += {.json,.jsonl,.csv,.html,.js,.j2,.toml,.py};
      teste com marcador sintético por formato; PRIVACY.md exato + commits
- [ ] F6.3 `check_real_data.py`: .json via scan de conteúdo + commits
- [ ] F6.4 `make serve` launcher loopback-only (recusa INTAKE_HOST não-loopback sem flag) + teste + commits
- [ ] F6.5 `demo_transcribe.py` exige --allow-external; `local_vlm.py:152` valida loopback salvo
      INTAKE_VLM_ALLOW_REMOTE=1 + testes + commits
- [ ] F6.V loop: purge real + cockpit degrada limpo (imagem 404 → layout textual)
- [ ] F6.PR fechamento

### F7 — CI eval-safety (SSI-1010)
- [ ] F7.1 `eval_extraction_synthetic.py`: --output-dir (SUMMARY_PATH hardcoded hoje na linha 56) + commits
- [ ] F7.2 bucket `unknown` nos 2 evals (não é false nem missed) + commits
- [ ] F7.3 métrica `unsafe_clean_count` + `make eval-safety` (gates: false_incident==0,
      unsafe_clean_count==0, recall estrutural 1.0) + commits
- [ ] F7.4 CI: job eval-safety (+ tesseract-ocr-por no runner); test split permanece congelado + commit
- [ ] F7.PR fechamento (saída real do eval-safety aqui)

### F8 — Showcase honesto (SSI-1011)
- [ ] F8.1 `make demo` one-command: fixture sintética → Tesseract REAL → uvicorn 127.0.0.1 → URL + commits
- [ ] F8.2 GIF do cockpit via Playwright screencast na fixture sintética → assets/ + commits
- [ ] F8.3 README: topo "In 30 seconds" EN, linha 1 honesta sobre cursiva, GIF, 4 diferenciais
      (browser-smoke CI, eval anti-memorização que publicou gate falho, ~599 testes $0,
      anti-corruption Raw/Normalized), Mermaid; limitações depois do valor + commits
- [ ] F8.4 docs/: STATUS_PR1.md, SSI-1002_EVIDENCE.md, STATUS_TIER_C.md → docs/archive/ + commit
- [ ] F8.V loop: clone limpo → make demo → roteiro 0/1/N + S/A + bloqueios no browser
- [ ] F8.PR fechamento

### F9 — Narrativa menor (SSI-1012)
- [ ] F9.1 watcher/reconciler/AnthropicLLM marcados experimentais (docstring+README, sem deletar) + commits
- [ ] F9.2 F-09: constantes table_rules.py:27-28 comentadas "piso heurístico deliberado <0.70" + commit
- [ ] F9.PR fechamento

### F10 — Bake-off PP-OCRv5 (SSI-1013, timeboxed, NÃO bloqueia release)
- [ ] F10.1 timebox de instalação: pip install paddleocr/paddlepaddle Windows nativo; falhou →
      registrar veto no READER_DECISION.md e pular p/ F11 + commit
- [ ] F10.2 `PaddleOCRVisionClient` atrás do VisionClient (factory + INTAKE_VISION=paddle_ocr) + testes mock + commits
- [ ] F10.3 `make eval-synthetic VISION=paddle_ocr SPLIT=val` vs baseline; critérios
      READER_DECISION (false_incident=0, chars_to_type ≤ baseline, VRAM ≤3GB); promove SÓ se
      vencer; registrar rodada + commit
- [ ] F10.PR fechamento

### F11 — Release v1.0.0 (SSI-1014)
- [ ] F11.1 make check → privacy-check → eval-safety (saídas reais aqui)
- [ ] F11.2 única rodada test-split do milestone (publica o que der, incl. bucket unknown)
- [ ] F11.3 make demo: roteiro manual 0/1/N, S/A, approve→edit→send bloqueado
- [ ] F11.4 make purge-demo-data + `git ls-files private` vazio
- [ ] F11.5 README com números do run; mover for_codex.md → docs/archive/
- [ ] F11.6 tag v1.0.0 (só após tudo verde); DoD = checklist §9 da auditoria
