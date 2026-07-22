"""Template "Controle de ocorrências": SheetSurface → imagem + ideal_lines.

Restrições AMARRADAS ao parser (src/clients/table_rules.py — contrato §11; cada uma
tem asserção em tests/test_template_controle.py):
- rótulos do cabeçalho ⊂ `ocr_aliases` da config (variantes A/B/C abaixo);
- a linha de colunas contém "Item … Descrição" (casa `_COLHDR`);
- `S/A` desenhado como LINHA ISOLADA na região da tabela (casa `_SA`);
- "Ronda" desenhado após a tabela (casa `_FOOTER`) — e NUNCA dentro dela;
- ocorrências separadas por LINHA EM BRANCO em `ideal_lines` (senão `_extract_rows`
  funde duas ocorrências numa row só);
- hora dupla na MESMA célula; `resolvido` como sim/não.

`ideal_lines` é o texto EXATAMENTE como desenhado, linha a linha (leitura ideal):
alimenta o gate G-S0 (`ideal_lines → RuleBasedTableExtractor → normalize`) a $0,
sem OCR. Marcadores `[risc:…]` são instrução visual (strikethrough), não texto —
em `ideal_lines` entram sem o marcador (palavra riscada continua visível). Campo
`legibility: illegible` vira rabisco na imagem e o token `[ilegível]` na leitura
ideal (a recusa correta é o comportamento premiado — contrato §2.2).

Higiene de IP (contrato §7): estrutura GENÉRICA de cabeçalho + tabela de 5 colunas;
nenhuma reprodução da arte/diagramação do formulário real.
"""

from __future__ import annotations

import random
from typing import Literal, NamedTuple

from PIL import Image, ImageDraw, ImageFont

from data.generators.canvas import (
    RENDER_HEIGHT,
    RENDER_WIDTH,
    draw_handwritten,
    wrap_handwritten,
)
from data.generators.fonts import Font, discover_handwriting_fonts
from data.generators.messiness_table import SheetSurface
from data.generators.occurrences import SheetRecord
from data.generators.surface_ops import CROSSOUT_CLOSE, CROSSOUT_OPEN

Variant = Literal["controle_A", "controle_B", "controle_C"]
VARIANTS: tuple[Variant, ...] = ("controle_A", "controle_B", "controle_C")
# Variante C: SÓ no split de test (held-out de layout, contrato §5) — imposto na PR-D5.
TEST_ONLY_VARIANTS: tuple[Variant, ...] = ("controle_C",)

# Rótulos impressos em ASCII: a fonte default do Pillow (rótulos "impressos") não
# cobre Ê/ç/ã (medido na amostra sample_tc-000000: tofu). "Descricao"/"Acao" estão
# nos ocr_aliases da config; acentos impressos voltam se um dia bundlarmos fonte
# impressa OFL. Os VALORES manuscritos usam as fontes OFL (acentos verificados).
_TITLE = "CONTROLE DE OCORRENCIAS"
_ILEGIVEL = "[ilegível]"

# Rótulos por variante — todos dentro dos ocr_aliases de configs/controle_ocorrencias.yaml.
_HEADER_LABELS: dict[Variant, tuple[str, str, str]] = {
    "controle_A": ("Data e Turno", "Vigilantes", "Unidade"),
    "controle_B": ("Data:", "Vigilante:", "Unidade:"),
    "controle_C": ("Data e Turno:", "Vigilantes:", "Unidade:"),
}
# Deslocamento horizontal do bloco de cabeçalho (variante C é deslocada).
_HEADER_X_OFFSET: dict[Variant, int] = {"controle_A": 0, "controle_B": 0, "controle_C": 90}

_COLUMNS: tuple[tuple[str, int], ...] = (
    ("Item", 150),
    ("Hora", 120),
    ("Descricao da Ocorrencia", 360),
    ("Acao", 190),
    ("Resolvido", 100),
)

_MARGIN = 40
_N_GRID_ROWS = 9  # assunção registrada (8–10 linhas na folha real)
_ROW_HEIGHT = 96
_SUBLINE_GAP = 28
_INK = (15, 20, 60)
_PRINT = (0, 0, 0)


class RenderResult(NamedTuple):
    """Saída do template (contrato §2: `font` vai para o bloco synthetic do gabarito)."""

    image: Image.Image
    ideal_lines: list[str]
    font_name: str


def _pick_font(rng: random.Random, size: int) -> tuple[Font, str]:
    """Uma "mão" por folha, com nome rastreável para o gabarito."""
    paths = discover_handwriting_fonts()
    if paths:
        chosen = rng.choice(paths)
        return ImageFont.truetype(str(chosen), size=size), chosen.stem
    return ImageFont.load_default(size=size), "pillow-default"


def _split_crossout(text: str) -> list[tuple[str, bool]]:
    """Segmentos (texto, riscado?) a partir dos marcadores [risc:…] da messiness."""
    parts: list[tuple[str, bool]] = []
    rest = text
    while CROSSOUT_OPEN in rest:
        pre, _, tail = rest.partition(CROSSOUT_OPEN)
        struck, _, rest = tail.partition(CROSSOUT_CLOSE)
        if pre:
            parts.append((pre, False))
        parts.append((struck, True))
    if rest:
        parts.append((rest, False))
    return parts


def _plain(text: str) -> str:
    """Texto sem marcadores (o que uma leitura ideal transcreveria)."""
    return "".join(seg for seg, _ in _split_crossout(text)).strip()


def _draw_value(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: Font,
    rng: random.Random,
) -> None:
    """Valor manuscrito; segmentos [risc:…] ganham strikethrough real."""
    x, y = xy
    for seg, struck in _split_crossout(text):
        draw_handwritten(draw, (x, y), seg, font, rng)
        width = int(font.getlength(seg))
        if struck:
            draw.line([(x, y + 12), (x + width, y + 14)], fill=_INK, width=2)
        x += width + 4


def _scribble(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], width: int, rng: random.Random
) -> None:
    """Rabisco ilegível: traços sobrepostos ocupando a largura da célula."""
    x, y = xy
    for _ in range(4):
        points = [(x + i * 12, y + 8 + rng.randint(-6, 6)) for i in range(max(2, width // 12))]
        draw.line(points, fill=_INK, width=2)


def render_sheet(
    rng: random.Random,
    record: SheetRecord,
    surface: SheetSurface,
    variant: Variant = "controle_A",
) -> RenderResult:
    """Renderiza a folha e devolve (imagem, leitura ideal linha a linha, fonte)."""
    canvas = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), "white")
    draw = ImageDraw.Draw(canvas)
    label_font = ImageFont.load_default(size=22)
    title_font = ImageFont.load_default(size=30)
    value_font, font_name = _pick_font(rng, size=24)
    ideal: list[str] = []

    # --- título (impresso) ---
    draw.text((_MARGIN, 40), _TITLE, font=title_font, fill=_PRINT)
    draw.line([(_MARGIN, 84), (RENDER_WIDTH - _MARGIN, 84)], fill=_PRINT, width=2)
    ideal.append(_TITLE)

    # --- cabeçalho: um rótulo por linha (valor na MESMA linha — find_after_label) ---
    labels = _HEADER_LABELS[variant]
    values = (surface.data_text, surface.vigilantes_text, surface.unidade_text)
    x0 = _MARGIN + _HEADER_X_OFFSET[variant]
    y = 110
    for label, value in zip(labels, values, strict=True):
        draw.text((x0, y), label, font=label_font, fill=_PRINT)
        _draw_value(draw, (x0 + int(label_font.getlength(label)) + 12, y), value, value_font, rng)
        ideal.append(f"{label} {value}")
        y += 46

    # --- grade da tabela (impressa) + linha de colunas ---
    table_top = y + 18
    col_edges = [_MARGIN]
    for _, width in _COLUMNS:
        col_edges.append(col_edges[-1] + width)
    header_h = 34
    table_bottom = table_top + header_h + _N_GRID_ROWS * _ROW_HEIGHT
    for edge in col_edges:
        draw.line([(edge, table_top), (edge, table_bottom)], fill=_PRINT, width=1)
    draw.line([(_MARGIN, table_top), (col_edges[-1], table_top)], fill=_PRINT, width=1)
    for i in range(_N_GRID_ROWS + 1):
        yy = table_top + header_h + i * _ROW_HEIGHT
        draw.line([(_MARGIN, yy), (col_edges[-1], yy)], fill=_PRINT, width=1)
    for (name, _), x_cell in zip(_COLUMNS, col_edges[:-1], strict=False):
        draw.text((x_cell + 6, table_top + 6), name, font=label_font, fill=_PRINT)
    ideal.append("  ".join(name for name, _ in _COLUMNS))

    # --- conteúdo da tabela ---
    row_y = table_top + header_h + 8
    if record.sem_alteracao:
        if record.riscado:
            # Células riscadas: traços atravessando a região, sem texto.
            draw.line(
                [(_MARGIN + 10, row_y + 10), (col_edges[-1] - 10, table_bottom - 20)],
                fill=_INK,
                width=3,
            )
            draw.line(
                [(_MARGIN + 10, table_bottom - 20), (col_edges[-1] - 10, row_y + 10)],
                fill=_INK,
                width=3,
            )
        else:
            _draw_value(draw, (col_edges[2] + 8, row_y), "S/A", value_font, rng)
            ideal.append("S/A")
    else:
        desc_width = _COLUMNS[2][1] - 16
        for i, row in enumerate(surface.rows):
            yy = row_y + i * _ROW_HEIGHT
            illegible = surface.legibility.get(f"ocorrencias[{i}].descricao") == "illegible"
            desc_lines = (
                []
                if illegible
                else wrap_handwritten(row.descricao or "", value_font, desc_width)[:3]
            )
            if illegible:
                _scribble(draw, (col_edges[2] + 8, yy), desc_width, rng)
            cells = [
                (col_edges[0] + 6, row.item),
                (col_edges[1] + 6, row.hora),
                (col_edges[2] + 8, desc_lines[0] if desc_lines else None),
                (col_edges[3] + 6, row.acao),
                (col_edges[4] + 6, row.resolvido),
            ]
            first_line_parts: list[str] = []
            for x_cell, text in cells:
                if text:
                    _draw_value(draw, (x_cell, yy), text, value_font, rng)
                    first_line_parts.append(_plain(text))
            if illegible:
                first_line_parts.insert(2 if row.hora else 1, _ILEGIVEL)
            ideal.append("  ".join(first_line_parts))
            for j, extra in enumerate(desc_lines[1:], start=1):
                _draw_value(draw, (col_edges[2] + 8, yy + j * _SUBLINE_GAP), extra, value_font, rng)
                ideal.append(_plain(extra))
            ideal.append("")  # linha em branco: separa rows para _extract_rows (§11.3)

    # --- rodapé (impresso; ÚNICO lugar com a palavra do _FOOTER) ---
    footer_y = table_bottom + 24
    draw.text((_MARGIN, footer_y), "Ronda", font=label_font, fill=_PRINT)
    draw.line(
        [(_MARGIN + 90, footer_y + 20), (RENDER_WIDTH - _MARGIN, footer_y + 20)],
        fill=_PRINT,
        width=1,
    )
    ideal.append("Ronda")

    return RenderResult(image=canvas, ideal_lines=ideal, font_name=font_name)
