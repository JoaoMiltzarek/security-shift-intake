# Formato da curadoria (ground-truth das folhas reais)

> **Privacidade.** Os arquivos de curadoria contêm dados reais (nomes, horários, descrições) e vivem
> **somente em `private/curadoria/`** (gitignored). Este documento descreve **apenas o formato** — o
> exemplo abaixo é **sintético/anonimizado**. Nenhuma curadoria real é versionada (plano R6 + regra #2).

A curadoria é a verdade de referência usada pela auditoria (`evals/eval_extraction_real.py`) para medir o
que o sistema extraiu vs. o que a folha realmente diz. Cada folha real vira um JSON em
`private/curadoria/<document_id>.json`, no **mesmo vocabulário do `RawDocumentExtraction`** (plano R1).

## Campos

| Campo | Tipo | Descrição |
|---|---|---|
| `schema_version` | string | Versão do formato (atual: `"1.0"`). Permite evoluir sem quebrar auditorias antigas. |
| `document_id` | string | Identificador estável da folha (kebab-case). |
| `source_file` | string | Caminho do arquivo real em `private/reais/` (PDF/JPG/PNG). |
| `review_status` | enum | `draft_by_claude` \| `needs_review` \| `verified_by_user` \| `synthetic_ground_truth`. |
| `truth_source` | enum (opcional) | `human_curation` (default implícito das curadorias reais) \| `generator` (gabarito sintético). Torna a origem explícita mesmo se o arquivo for copiado de lugar. |
| `cabecalho.data` | string\|null | Data e turno como escritos. |
| `cabecalho.turno` | string\|null | Turno, se separável da data. |
| `cabecalho.vigilantes` | string[] | Lista de vigilantes (a folha real tem **vários**). |
| `cabecalho.unidade` | string\|null | Unidade/posto. |
| `sem_alteracao` | bool | `true` se a folha não teve ocorrência (tudo `S/A`). |
| `riscado` | bool | `true` se as células de descrição estão riscadas (= sem ocorrência). |
| `ocorrencias` | objeto[] | Uma entrada por linha real da tabela (vazio se `sem_alteracao`/`riscado`). |
| `ocorrencias[].item` | string | Tópico principal (ex.: crachá, acesso, alarme, portão). |
| `ocorrencias[].hora_entrada` | string\|null | Hora; quando há duas, esta é a de **entrada/acesso**. |
| `ocorrencias[].hora_saida` | string\|null | Hora de **saída** (só quando a folha registra duas horas). |
| `ocorrencias[].descricao` | string | Descrição da ocorrência — **o campo de maior fidelidade** (junto de `item`). |
| `ocorrencias[].acao` | string\|null | Ação tomada. |
| `ocorrencias[].resolvido` | string\|null | `sim` \| `nao` \| null. |
| `notes` | string (opcional) | Observações do curador (leituras incertas, messiness de preenchimento). |

## `review_status` (plano R4 — quality gate)

- `draft_by_claude` — primeira transcrição automática; **não** é verdade absoluta.
- `needs_review` — marcada para conferência humana.
- `verified_by_user` — conferida pelo usuário. **Só este status conta como ground-truth na auditoria
  final**; os demais entram apenas como pendentes de conferência.
- `synthetic_ground_truth` — verdade **gerada** pela fábrica sintética
  (`docs/DATASET_CONTRACT.md`), acompanhada de `truth_source: "generator"`. **Nunca significa
  verificação humana**, **nunca aparece em `private/curadoria/`** e o eval real a **ignora por
  default** (filtro `VALID_REVIEW_STATUS` inalterado); só o eval sintético a aceita, por opt-in
  explícito. A distinção é semântica por construção: verdade gerada é perfeita por definição do
  gerador, não por conferência — confundir as duas seria apresentar mock como funcionalidade.

## `S/A` e risco

`S/A` (sem alteração) ou células riscadas significam **ausência de ocorrência**. Devem produzir
`ocorrencias: []` e `sem_alteracao`/`riscado = true` — **nunca** uma ocorrência (evita `FALSE_INCIDENT`).

## Exemplo (sintético/anonimizado)

```json
{
  "schema_version": "1.0",
  "document_id": "doc-exemplo-acesso",
  "source_file": "private/reais/exemplo.pdf",
  "review_status": "verified_by_user",
  "cabecalho": {
    "data": "01/01/26",
    "turno": null,
    "vigilantes": ["Vigilante A", "Vigilante B"],
    "unidade": "Posto Exemplo"
  },
  "sem_alteracao": false,
  "riscado": false,
  "ocorrencias": [
    {
      "item": "Acesso",
      "hora_entrada": "HH:MM",
      "hora_saida": "HH:MM",
      "descricao": "Prestador de serviço acessa para manutenção, acompanhado.",
      "acao": "Registrado em livro.",
      "resolvido": "sim"
    }
  ],
  "notes": "Hora dupla = entrada e saída."
}
```
