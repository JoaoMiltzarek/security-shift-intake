"""Tier C: gerador do gabarito limpo da folha "Controle de ocorrências".

O registro gerado JÁ nasce no vocabulário da curadoria (docs/CURADORIA_FORMATO.md),
então `to_curadoria_dict` + eval sintético reusam as fórmulas do eval real sem
tradução (docs/DATASET_CONTRACT.md §2). Conteúdo 100% fictício por construção
(contrato §7): listas fixas revisadas em PR, nunca geradas por LLM em runtime.

Invariante central (contrato §2.2): `data` carrega EXATAMENTE a string que será
desenhada no campo "Data e Turno" ("DD/MM/AAAA - Turno") — a régua compara
`data_turno` (sistema) × `cabecalho.data` (gabarito) por CER.

Held-out anti-memorização (contrato §5 / gate G-S3): ~20% dos nomes, unidades e
templates de descrição-ação existem SÓ no split de test (`vocab_for_split`).

Determinismo: toda aleatoriedade flui por um `random.Random` injetado; o held-out
tem seed própria, registrada no meta.json pela PR-D5.
"""

from __future__ import annotations

import random
import string
from datetime import date, timedelta
from typing import Literal, NamedTuple

from pydantic import BaseModel

from data.generators import occurrence_priors as priors

_EPOCH = date(2026, 1, 1)
_DATE_SPAN_DAYS = 365

Profile = Literal["balanced", "operational"]
Split = Literal["train", "val", "test"]

HELDOUT_FRACTION = 0.20  # contrato §5: fração exclusiva do test por dimensão
DEFAULT_HELDOUT_SEED = 7

# Janelas de hora coerentes com o turno (Dia/Noite).
_DAY_HOURS = range(6, 18)
_NIGHT_HOURS = [*range(18, 24), *range(0, 6)]

# Vocabulários fictícios de apoio aos placeholders (contrato §7).
_SETORES = [
    "Setor A",
    "Setor B",
    "Setor C",
    "pátio",
    "doca de carga",
    "recepção",
    "almoxarifado",
    "estacionamento",
]
_EMPRESAS = [
    "TransNorte Ltda",
    "Serviços Alfa",
    "Grupo Vetor",
    "Limpar Facilities",
    "TecnoRonda",
]
_NOMES_TERCEIROS = [
    "Sr. Nogare",
    "Sra. Talvane",
    "Sr. Ubirajara",
    "Sra. Vandira",
    "Sr. Waldeci",
]


class OccurrenceTemplate(NamedTuple):
    """Um template de linha da tabela: item + descrição parametrizada + ações."""

    item: str
    descricao: str
    acoes: tuple[str, ...]
    com_hora: bool = True


# ~18 tipos de item do domínio (decisão registrada: tipos são CONTEÚDO de linha,
# não layouts). 2 templates por tipo; placeholders preenchidos por _fill().
OCCURRENCE_BANK: tuple[OccurrenceTemplate, ...] = (
    OccurrenceTemplate(
        "Ambulância",
        "Entrada de ambulância para atendimento no {setor}.",
        ("Acesso liberado e registrado.", "Acompanhado até o local."),
    ),
    OccurrenceTemplate(
        "Ambulância",
        "Saída de ambulância após atendimento, sem intercorrência.",
        ("Registrado em livro.",),
    ),
    OccurrenceTemplate(
        "Veículo não autorizado",
        "Veículo placa {placa} estacionado em vaga restrita.",
        ("Condutor orientado a retirar.", "Acionada a supervisão."),
    ),
    OccurrenceTemplate(
        "Veículo não autorizado",
        "Veículo {placa} tentou acesso pela doca sem agendamento.",
        ("Acesso negado e registrado.",),
    ),
    OccurrenceTemplate(
        "Alarme",
        "Alarme disparou no {setor}, verificação sem anormalidade.",
        ("Verificação no local realizada.", "Alarme rearmado."),
    ),
    OccurrenceTemplate(
        "Alarme",
        "Alarme de incêndio acionado por engano no {setor}.",
        ("Brigada comunicada e sistema rearmado.",),
    ),
    OccurrenceTemplate(
        "Falta de energia",
        "Queda de energia no {setor}, gerador assumiu.",
        ("Manutenção comunicada.", "Acompanhado até normalizar."),
    ),
    OccurrenceTemplate(
        "Falta de energia",
        "Oscilação de energia derrubou câmeras por alguns minutos.",
        ("Registrado e monitorado.",),
    ),
    OccurrenceTemplate(
        "Porta aberta",
        "Porta do {setor} encontrada aberta durante a inspeção.",
        ("Porta fechada e conferida.", "Responsável do setor avisado."),
        False,
    ),
    OccurrenceTemplate(
        "Porta aberta",
        "Janela do {setor} encontrada destravada.",
        ("Travada e registrada.",),
        False,
    ),
    OccurrenceTemplate(
        "Visitante sem crachá",
        "Visitante {nome} circulando sem crachá no {setor}.",
        ("Orientado e encaminhado à recepção.",),
    ),
    OccurrenceTemplate(
        "Visitante sem crachá",
        "Pessoa sem identificação na área do {setor}.",
        ("Abordagem feita, crachá emitido.",),
    ),
    OccurrenceTemplate(
        "Objeto esquecido",
        "Objeto esquecido no {setor} (mochila).",
        ("Recolhido para a portaria.", "Guardado para retirada."),
        False,
    ),
    OccurrenceTemplate(
        "Objeto esquecido",
        "Celular encontrado no {setor}.",
        ("Registrado em livro de achados.",),
        False,
    ),
    OccurrenceTemplate(
        "Prestador de serviço",
        "Prestador da {empresa} em manutenção no {setor}, acompanhado.",
        ("Acompanhamento até o término.",),
    ),
    OccurrenceTemplate(
        "Prestador de serviço",
        "Equipe da {empresa} realiza limpeza técnica no {setor}.",
        ("Acesso registrado e supervisionado.",),
    ),
    OccurrenceTemplate(
        "Troca de turno",
        "Troca de turno realizada com passagem de serviço.",
        ("Livro conferido e assinado.",),
    ),
    OccurrenceTemplate(
        "Troca de turno",
        "Assumido o posto com chaves e rádio conferidos.",
        ("Sem pendências na passagem.",),
    ),
    OccurrenceTemplate(
        "Inspeção",
        "Inspeção completa no perímetro sem anormalidades.",
        ("Registrado no bastão de controle.",),
    ),
    OccurrenceTemplate(
        "Inspeção", "Inspeção no {setor} identificou fiação exposta.", ("Manutenção acionada.",)
    ),
    OccurrenceTemplate(
        "Acesso",
        "Acesso de {nome} autorizado pela supervisão fora do horário.",
        ("Registrado com autorização.",),
    ),
    OccurrenceTemplate(
        "Acesso",
        "Tentativa de acesso sem autorização pela portaria.",
        ("Acesso negado e supervisão avisada.",),
    ),
    OccurrenceTemplate(
        "Comunicado",
        "Comunicado recebido sobre obra programada no {setor}.",
        ("Equipe do turno informada.",),
        False,
    ),
    OccurrenceTemplate(
        "Comunicado",
        "Aviso de mudança no procedimento de entrada de veículos.",
        ("Fixado no mural da guarita.",),
        False,
    ),
    OccurrenceTemplate(
        "Crachá", "Crachá encontrado no {setor}.", ("Devolvido à recepção.",), False
    ),
    OccurrenceTemplate(
        "Crachá",
        "Colaborador esqueceu o crachá, acesso mediante registro.",
        ("Registrado e liberado.",),
    ),
    OccurrenceTemplate(
        "Portão",
        "Portão automático do {setor} travou aberto.",
        ("Manutenção acionada, vigilância reforçada.",),
    ),
    OccurrenceTemplate(
        "Portão", "Portão da doca com sensor falhando.", ("Operação manual até reparo.",)
    ),
    OccurrenceTemplate(
        "Iluminação", "Iluminação queimada no {setor}.", ("Aberto chamado de manutenção.",), False
    ),
    OccurrenceTemplate(
        "Iluminação", "Refletor piscando no {setor}.", ("Registrado para troca.",), False
    ),
    OccurrenceTemplate("CFTV", "Câmera do {setor} sem imagem.", ("Chamado técnico aberto.",)),
    OccurrenceTemplate(
        "CFTV",
        "Gravador reiniciou sozinho, imagens normalizadas.",
        ("Monitorado o restante do turno.",),
    ),
    OccurrenceTemplate(
        "Entrega de material",
        "Entrega da {empresa} recebida na doca.",
        ("Conferida e encaminhada.",),
    ),
    OccurrenceTemplate(
        "Entrega de material",
        "Retirada de material autorizada para {empresa}.",
        ("Nota conferida na saída.",),
    ),
    OccurrenceTemplate(
        "Perturbação",
        "Barulho vindo do {setor}, verificação sem anormalidade.",
        ("Verificação extra no local.",),
    ),
    OccurrenceTemplate(
        "Perturbação", "Discussão entre terceiros no estacionamento.", ("Mediado e dispersado.",)
    ),
)


class SheetOccurrence(BaseModel):
    """Uma linha da tabela (vocabulário da curadoria)."""

    item: str
    hora_entrada: str | None = None
    hora_saida: str | None = None
    descricao: str
    acao: str | None = None
    resolvido: str | None = None  # "sim" | "nao" | None (em branco)


class SheetRecord(BaseModel):
    """Uma folha "Controle de ocorrências" (verdade limpa, formato curadoria)."""

    document_id: str
    data: str  # string EXATA desenhada no campo "Data e Turno" (contrato §2.2)
    turno: str
    vigilantes: list[str]
    unidade: str
    sem_alteracao: bool
    riscado: bool
    ocorrencias: list[SheetOccurrence]
    profile: str


class SheetVocabulary(NamedTuple):
    """Vocabulário disponível para um split (held-out aplicado)."""

    guards: tuple[str, ...]
    unidades: tuple[str, ...]
    bank: tuple[OccurrenceTemplate, ...]


def partition_heldout(
    items: tuple[str, ...] | tuple[OccurrenceTemplate, ...],
    fraction: float,
    rng: random.Random,
) -> tuple[list[int], list[int]]:
    """Índices (shared, test_only) — test_only tem ~fraction dos itens, mínimo 1."""
    indices = list(range(len(items)))
    rng.shuffle(indices)
    n_test = max(1, round(len(items) * fraction))
    return sorted(indices[n_test:]), sorted(indices[:n_test])


def vocab_for_split(
    split: Split,
    heldout_seed: int = DEFAULT_HELDOUT_SEED,
    fraction: float = HELDOUT_FRACTION,
) -> SheetVocabulary:
    """Vocabulário do split: train/val só a parte shared; test vê o conjunto todo.

    Mesma seed ⇒ mesma partição (registrada no meta.json pela PR-D5).
    """
    rng = random.Random(heldout_seed)
    guards = tuple(priors.GUARD_NAMES)
    unidades = tuple(priors.UNIDADES)
    bank = OCCURRENCE_BANK
    g_shared, _ = partition_heldout(guards, fraction, rng)
    u_shared, _ = partition_heldout(unidades, fraction, rng)
    b_shared, _ = partition_heldout(bank, fraction, rng)
    if split == "test":
        return SheetVocabulary(guards, unidades, bank)
    return SheetVocabulary(
        tuple(guards[i] for i in g_shared),
        tuple(unidades[i] for i in u_shared),
        tuple(bank[i] for i in b_shared),
    )


def _sample_int(rng: random.Random, dist: dict[int, float]) -> int:
    values = list(dist.keys())
    weights = list(dist.values())
    return rng.choices(values, weights=weights, k=1)[0]


def _placa(rng: random.Random) -> str:
    """Placa fictícia no padrão Mercosul (LLLNLNN) — contrato §7."""
    up = string.ascii_uppercase
    return (
        "".join(rng.choice(up) for _ in range(3))
        + str(rng.randint(0, 9))
        + rng.choice(up)
        + f"{rng.randint(0, 99):02d}"
    )


def _hora(rng: random.Random, turno: str) -> str:
    hours = list(_DAY_HOURS) if turno == "Dia" else list(_NIGHT_HOURS)
    return f"{rng.choice(hours):02d}:{rng.randint(0, 59):02d}"


def _hora_saida(rng: random.Random, entrada: str) -> str:
    """Saída 10–120 min após a entrada (mod 24h — turno noturno cruza a meia-noite)."""
    h, m = int(entrada[:2]), int(entrada[3:])
    total = (h * 60 + m + rng.randint(10, 120)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _fill(rng: random.Random, template: str) -> str:
    return template.format(
        setor=rng.choice(_SETORES),
        placa=_placa(rng),
        empresa=rng.choice(_EMPRESAS),
        nome=rng.choice(_NOMES_TERCEIROS),
    )


def _occurrence(rng: random.Random, turno: str, vocab: SheetVocabulary) -> SheetOccurrence:
    tpl = rng.choice(vocab.bank)
    entrada = _hora(rng, turno) if tpl.com_hora else None
    saida = (
        _hora_saida(rng, entrada)
        if entrada is not None and rng.random() < priors.P_HORA_DUPLA
        else None
    )
    resolvido_raw = rng.choices(
        list(priors.P_RESOLVIDO.keys()), weights=list(priors.P_RESOLVIDO.values()), k=1
    )[0]
    return SheetOccurrence(
        item=tpl.item,
        hora_entrada=entrada,
        hora_saida=saida,
        descricao=_fill(rng, tpl.descricao),
        acao=rng.choice(tpl.acoes),
        resolvido=None if resolvido_raw == "em_branco" else resolvido_raw,
    )


def generate_sheet(
    rng: random.Random,
    doc_id: str,
    profile: Profile = "balanced",
    vocab: SheetVocabulary | None = None,
) -> SheetRecord:
    """Gera uma folha limpa (verdade) segundo os priors do contrato §6."""
    if vocab is None:
        vocab = vocab_for_split("test")  # conjunto completo por default (uso avulso)

    turno = "Dia" if rng.random() < priors.P_SHIFT_PERIOD["day"] else "Noite"
    d = _EPOCH + timedelta(days=rng.randint(0, _DATE_SPAN_DAYS - 1))
    data_display = f"{d.day:02d}/{d.month:02d}/{d.year} - {turno}"

    n_vig = _sample_int(rng, priors.P_N_VIGILANTES)
    vigilantes = rng.sample(list(vocab.guards), n_vig)
    unidade = rng.choice(vocab.unidades)

    sem_alteracao = rng.random() < priors.P_SA_GIVEN_PROFILE[profile]
    riscado = sem_alteracao and rng.random() < priors.P_RISCADO_GIVEN_NO_OCCURRENCE
    ocorrencias: list[SheetOccurrence] = []
    if not sem_alteracao:
        n_occ = _sample_int(rng, priors.P_N_OCORRENCIAS_GIVEN_OCCURRENCE)
        ocorrencias = [_occurrence(rng, turno, vocab) for _ in range(n_occ)]

    return SheetRecord(
        document_id=doc_id,
        data=data_display,
        turno=turno,
        vigilantes=vigilantes,
        unidade=unidade,
        sem_alteracao=sem_alteracao,
        riscado=riscado,
        ocorrencias=ocorrencias,
        profile=profile,
    )


def to_curadoria_dict(record: SheetRecord, source_file: str) -> dict[str, object]:
    """Serializa no formato da curadoria + semântica sintética (contrato §2).

    O bloco `synthetic` (template/difficulty/font/messiness/surface) é acrescentado
    pela orquestração (PR-D5), que conhece o render — aqui só a verdade limpa.
    """
    return {
        "schema_version": "1.0",
        "document_id": record.document_id,
        "source_file": source_file,
        "review_status": "synthetic_ground_truth",
        "truth_source": "generator",
        "cabecalho": {
            "data": record.data,  # string exata desenhada (contrato §2.2)
            "turno": record.turno,
            "vigilantes": list(record.vigilantes),
            "unidade": record.unidade,
        },
        "sem_alteracao": record.sem_alteracao,
        "riscado": record.riscado,
        "ocorrencias": [
            {
                "item": o.item,
                "hora_entrada": o.hora_entrada,
                "hora_saida": o.hora_saida,
                "descricao": o.descricao,
                "acao": o.acao,
                "resolvido": o.resolvido,
            }
            for o in record.ocorrencias
        ],
    }
