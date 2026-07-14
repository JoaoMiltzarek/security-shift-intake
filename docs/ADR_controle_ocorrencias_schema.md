# ADR — Suporte à folha "Controle de ocorrências" (tabela de N linhas)

- **Status:** Aceito e implementado. Semântica de disposição endurecida em 2026-07-11 para o
  contrato tri-state descrito abaixo.
- **Data:** 2026-06-24
- **Contexto-base:** [AUDITORIA_FOLHAS_REAIS.md](AUDITORIA_FOLHAS_REAIS.md) · [CURADORIA_FORMATO.md](CURADORIA_FORMATO.md)

> Exemplos JSON abaixo são **sintéticos/anonimizados**. Dados reais vivem só em `private/` (regra #2).

## 1. Problema

A config atual (`configs/htmicron_security.yaml`) modela um **incidente único** com 6 campos escalares
(`shift_date`, `guard_name` singular, `post`, `shift_period`, `incident_occurred`, `incident_description`).
A folha real é uma **tabela de N linhas** (`Item | Hora | Descrição | Ação | Resolvido`) com cabeçalho de
**vários vigilantes**, e usa `S/A`/risco para "sem alteração".

A auditoria do baseline (preliminar, 2 folhas rodadas) comprovou o impacto:
- **2 erros BLOCKER**: `MISSED_INCIDENT` (a ocorrência real não tem onde ser representada) e
  `FALSE_INCIDENT` (numa folha `S/A`, ruído de OCR virou "ocorrência" — risco operacional).
- `FIELD_NOT_FOUND` em todos os campos de cabeçalho (rótulos não batem: `Data e Turno`/`Vigilantes`/`Unidade`
  vs. `Data`/`Vigilante`/`Posto`).
- **0** ocorrências capturadas com fidelidade; **0** campos `accepted`.

O Tesseract lê rótulos impressos, mas valores cursivos viram ruído — limite conhecido do OCR livre (não é
defeito do pipeline). O problema central é **estrutural**, não de tuning.

## 2. Decisão proposta

Adotar a **remodelagem completa (caminho A)** com separação de modelos (plano R1/R2):

1. **`RawDocumentExtraction`** (acoplado ao layout): cabeçalho + linhas + células, cada campo com
   **metadados de auditoria** (`value`, `confidence`, `source`, `status`, `evidence`).
2. **`NormalizedIncidentModel`** (domínio estável): turno + lista de ocorrências normalizadas e
   disposição `unknown | none | present`. `none` exige evidência explícita de `S/A`/risco ou
   confirmação humana; zero linhas sem essa prova é `unknown`, nunca “sem ocorrência”.
3. **Estágio `normalize`** novo entre `extract` e `validate` (`Raw → Normalized`).
4. **Tipo de campo repetível ("table")** no schema (`src/schema/config.py`) + nova
   `configs/controle_ocorrencias.yaml`. A `htmicron_security.yaml` permanece intacta (coexistência).
5. **Quality gates (R4):** crítico por linha; gate de aprovação bloqueia draft com campo
   `must_review`/`missing`/`ambiguous`.

## 3. Alternativas consideradas

| # | Alternativa | Veredito | Porquê |
|---|---|---|---|
| A | **Raw+Normalized + tabela** (proposta) | **Escolhida** | Fiel à folha; isola domínio do layout; resolve BLOCKERs |
| B | Só tipo "tabela" no schema (sem Raw/Normalized) | Parcial | Captura linhas, mas acopla domínio ao layout; sem trilha de evidência/`source` |
| C | Melhoria leve (6 escalares + prompts/aliases) | Rejeitada | Não representa N linhas; `MISSED_INCIDENT`/`FALSE_INCIDENT` persistem |

## 4. Modelos (exemplos sintéticos)

**Campo auditado (R2)** — `AuditedField`:
```json
{"value": "Acesso", "confidence": 0.5, "source": "ocr", "status": "must_review", "evidence": "trecho OCR"}
```
`source ∈ {ocr, rule, human}` · `status ∈ {accepted, must_review, missing, ambiguous}`.

**`RawDocumentExtraction`** (o que foi lido da folha):
```json
{
  "schema_version": "1.0",
  "report_type": "controle_ocorrencias",
  "tabela_encontrada": true,
  "header": {
    "data_turno": {"value": "01/01", "confidence": 0.4, "source": "ocr", "status": "must_review", "evidence": "..."},
    "vigilantes": {"value": ["Vigilante A", "Vigilante B"], "confidence": 0.3, "source": "ocr", "status": "must_review", "evidence": "..."},
    "unidade": {"value": "Posto Exemplo", "confidence": 0.3, "source": "ocr", "status": "must_review", "evidence": "..."}
  },
  "rows": [
    {
      "item": {"value": "Acesso", "confidence": 0.5, "source": "ocr", "status": "must_review", "evidence": "..."},
      "hora": {"value": ["HH:MM", "HH:MM"], "confidence": 0.4, "source": "ocr", "status": "must_review", "evidence": "..."},
      "descricao": {"value": "Prestador acessa para manutenção.", "confidence": 0.4, "source": "ocr", "status": "must_review", "evidence": "..."},
      "acao": {"value": "Registrado em livro.", "confidence": 0.4, "source": "ocr", "status": "must_review", "evidence": "..."},
      "resolvido": {"value": "sim", "confidence": 0.5, "source": "ocr", "status": "must_review", "evidence": "..."},
      "sem_alteracao": false
    }
  ]
}
```

**`NormalizedIncidentModel`** (o que o domínio entende):
```json
{
  "schema_version": "1.1",
  "shift": {"date": "01/01", "period": null, "guards": ["Vigilante A", "Vigilante B"], "unit": "Posto Exemplo"},
  "disposition": "present",
  "no_occurrence": false,
  "occurrences": [
    {"category": "access", "entry_time": "HH:MM", "exit_time": "HH:MM",
     "description": "Prestador acessa para manutenção.", "action": "Registrado em livro.",
     "resolved": true, "needs_review": true}
  ]
}
```
Folha com explicit S/A evidence →
`{"schema_version": "1.1", "disposition": "none", "no_occurrence": true, "occurrences": []}`.
Tabela ausente ou sem linha legível → `disposition="unknown"`; unknown blocks approval and export.
`no_occurrence` permanece apenas como derived compatibility field calculado da disposição.

## 5. Consequências

**Positivas:** captura N ocorrências; `S/A` deixa de virar incidente; falha estrutural não é lavada como
“sem ocorrência”; trilha de evidência/`source` por campo;
domínio estável a mudanças de layout; auditoria reflete progresso por taxonomia/severidade.
**Negativas:** mudança maior (schema, estágio novo, crítico, template, geradores, testes); mais complexidade
no contrato; manter dois modelos sincronizados via `normalize`.

## 6. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Regressão no fluxo antigo | `htmicron_security.yaml` intacto; testes do mock/sintético continuam; `make check` por micro-etapa |
| OCR cursivo fraco (Tesseract) | Não é meta do ADR resolver HTR; valores baixos → `must_review` (humano corrige). Métrica honesta |
| Acoplamento acidental ao layout | `normalize` é a única fronteira; domínio não importa modelos `Raw` |
| Vazamento de PII em relatórios | `make privacy-check` + gate de PII no writer (R4) |
| Complexidade do tipo "tabela" no schema | Validar com "schema-for-the-schema" (Pydantic) + testes de config inválida |

## 7. Estratégia de migração

1. Modelos `Raw`/`Normalized` + `AuditedField` (novos, sem tocar no fluxo atual).
2. Tipo "table" no schema + `configs/controle_ocorrencias.yaml` (coexiste).
3. Estágio `normalize` + orchestrator seleciona caminho por `report_type`/config.
4. Crítico por linha + tratamento de `S/A` + gate (R4).
5. `RuleBasedLLMClient`/OCR para células/hora dupla/`S/A`.
6. Geradores sintéticos Tier A/B da nova estrutura (anonimizados).
7. Cada passo: teste (mock) + `make check` verde + commit.

## 8. Critérios de aceite

- `make demo-pipeline FILE=private/reais/<folha>` offline, sem API paga.
- Tabela de **N linhas** representável; **`S/A`/risco nunca vira ocorrência** (0 `FALSE_INCIDENT` em folhas S/A).
- Sem evidência explícita, zero linhas produz `unknown`, cria pendência e bloqueia aprovação/exportação.
- Ambíguo/baixa confiança → `must_review`; **draft não aprovável** com campo pendente (R4).
- Fluxo antigo (`htmicron_security.yaml`) + mock/sintético **não regridem**; `make check` verde.
- `git status` sem dado real; `make privacy-check` verde; relatório público sem PII.
- `eval_extraction_real` mostra **melhora** vs. baseline (menos BLOCKER/HIGH; ocorrências capturadas > 0).

## 9. Decisão

> **Aceito (2026-06-25):** o usuário aprovou o **caminho A** (Raw+Normalized+tabela) após revisar a
> auditoria. A Fase 3 segue em micro-etapas commitadas, preservando o fluxo `htmicron_security.yaml`.
