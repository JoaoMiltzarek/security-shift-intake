"""CLI for `make demo-pipeline-mock` — public synthetic demo, no file, no API, $0.

Runs the table pipeline (controle_ocorrencias) on SYNTHETIC, legible OCR text via the
mock vision client — so it works in a fresh clone with no real sheet and no Tesseract.
Creates two pending drafts (one incident, one "S/A") that mirror the standardized
output, then prints the review URLs.

This is the demo a recruiter runs first. Real sheets go through `make demo-pipeline`
(local Tesseract). Nothing is sent; everything stays behind the human gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.demo_pipeline import build_and_store
from src.api.db import make_engine
from src.classifier.rules import RuleBasedIncidentClassifier
from src.clients.mock import MockVisionClient

CONFIG = Path("configs/controle_ocorrencias.yaml")
# A committed synthetic image — only used so ingest has a page to load; the mock vision
# ignores it and returns the canned OCR text below.
SAMPLE = Path("samples/sample_doc-00000.png")

# Synthetic, fully legible "OCR" of a controle_ocorrencias sheet with one incident.
OCR_INCIDENT = """Controle de ocorrencias
Data e Turno 25/06/2026 diurno
Vigilantes Ana Silva, Bruno Costa
Unidade 1
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
Alarme 14:32 Alarme disparou 4 vezes no setor B Verificado, sem intrusao sim
Ronda x
Monitoramento de cameras x
"""

# Synthetic, fully legible "OCR" of a no-incident sheet (S/A).
OCR_NO_CHANGE = """Controle de ocorrencias
Data e Turno 25/06/2026 noturno
Vigilantes Otavio Lemos, Carla Dias
Unidade 2
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
S/A
S/A
Ronda x
"""

SCENARIOS = [("incidente (Alarme)", OCR_INCIDENT), ("sem alteração (S/A)", OCR_NO_CHANGE)]


def main(argv: list[str]) -> int:
    if not SAMPLE.exists():
        print(f"Sample sintético ausente: {SAMPLE} (rode `make gen-sheets`).", file=sys.stderr)
        return 2

    engine = make_engine()
    ids: list[int] = []
    for label, text in SCENARIOS:
        print(f"\n# Cenário sintético: {label}")
        vision = MockVisionClient(text=text, confidence=0.95)
        classifier = RuleBasedIncidentClassifier()
        ids.append(build_and_store(SAMPLE, vision, classifier, CONFIG, engine))

    print("\nRevise no navegador (suba a UI com a config de tabela):")
    print("  INTAKE_CONFIG=configs/controle_ocorrencias.yaml uv run uvicorn src.api.asgi:app")
    for draft_id in ids:
        print(f"  http://127.0.0.1:8000/drafts/{draft_id}/review")
    print("\nDados 100% sintéticos. Limpe com:  make purge-demo-data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
