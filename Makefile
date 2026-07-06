# Makefile — Definition-of-Done task runner for security-shift-intake.
# Recipes are kept to single, portable commands so they run under both POSIX sh
# (CI / Linux) and Windows cmd. Real targets land milestone by milestone; not-yet
# -implemented targets fail loudly so a DoD is never silently "green".

.DEFAULT_GOAL := help

# Config the real-file demo runs against. Defaults to the v1 occurrence-table sheet;
# override e.g. `make demo-pipeline FILE=... CONFIG=configs/htmicron_security.yaml`.
CONFIG ?= configs/controle_ocorrencias.yaml

# Sample cap for the BRESSAY real-handwriting eval (override: `make eval-bressay N=20`).
N ?= 50

# Instrumented real-sheet eval (docs/EVAL_PROTOCOL.md): reader + rasterization DPI.
# Override: `make eval-real VISION=local_vlm DPI=250 REAL_N=3`.
VISION ?= local_ocr
DPI ?= 150
REAL_N ?= 0

# Tier C canonical dataset name (docs/DATASET_CONTRACT.md par.4). Override:
# `make gen-sheets DATASET=bench-balanced`.
DATASET ?= smoke

.PHONY: help install lint format format-check typecheck test check \
        validate-config gen-data gen-pdfs gen-sheets demo-transcribe demo-pipeline \
        demo-pipeline-mock eval eval-bressay eval-real \
        purge-demo-data purge-real-data purge-all-private privacy-check

help:
	@echo security-shift-intake - available targets:
	@echo   make install         - sync the virtualenv from uv.lock
	@echo   make lint            - ruff lint
	@echo   make format          - ruff format (write)
	@echo   make format-check    - ruff format (check only)
	@echo   make typecheck       - mypy on src
	@echo   make test            - pytest
	@echo   make check           - lint + typecheck + test (the M0 DoD)
	@echo   make validate-config - [M1] validate configs against the schema
	@echo   make gen-data        - [M2] generate Tier A synthetic records
	@echo   make gen-pdfs        - [M3] render Tier B handwritten PDFs
	@echo   make gen-sheets      - [tier_c] generate occurrence-table sheets, DATASET=smoke/bench-balanced/bench-operational/stress
	@echo   make demo-transcribe - [M4] run the real VLM on one PDF (needs API key)
	@echo   make demo-pipeline   - local zero-cost end-to-end on a real FILE=... (OCR+rules, CONFIG=...)
	@echo   make demo-pipeline-mock - public synthetic demo (no file, no API)
	@echo   make purge-demo-data - wipe only temp demo artifacts (DB + audit/) in private/
	@echo   make purge-real-data - wipe real sheets (private/reais/), needs CONFIRM=YES
	@echo   make purge-all-private - wipe ALL of private/ (incl. curadoria), needs CONFIRM=YES
	@echo   make privacy-check   - verify no real data/PII tracked or outside private/
	@echo   make eval            - [M8] produce metrics.json + EVAL_REPORT.md
	@echo   make eval-bressay    - [v2] real BR-PT handwriting eval (BRESSAY); see docs/EVAL_BRESSAY.md
	@echo   make eval-real       - instrumented real-sheet eval, VISION=local_ocr/local_vlm/mock DPI=150; see docs/EVAL_PROTOCOL.md
	@echo   "  (reader: set INTAKE_VISION=local_vlm to use the local open VLM instead of Tesseract)"

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src data scripts

test:
	uv run pytest

# Convenience aggregate matching the M0 Definition of Done.
check: lint typecheck test

# --- Not implemented yet: fail loudly until the owning milestone lands. ---

validate-config:
	PYTHONPATH=. uv run python scripts/validate_config.py configs/htmicron_security.yaml configs/controle_ocorrencias.yaml

gen-data:
	PYTHONPATH=. uv run python scripts/gen_data.py

gen-pdfs:
	PYTHONPATH=. uv run python scripts/gen_pdfs.py

gen-sheets:
	PYTHONPATH=. uv run python scripts/gen_sheets.py --dataset $(DATASET)

demo-transcribe:
	PYTHONPATH=. uv run python scripts/demo_transcribe.py --file "$(FILE)"

demo-pipeline:
	PYTHONPATH=. uv run python scripts/demo_pipeline.py --file "$(FILE)" --config "$(CONFIG)"

demo-pipeline-mock:
	PYTHONPATH=. uv run python scripts/demo_pipeline_mock.py

purge-demo-data:
	PYTHONPATH=. uv run python scripts/purge_demo_data.py demo

purge-real-data:
	PYTHONPATH=. uv run python scripts/purge_demo_data.py real --confirm "$(CONFIRM)"

purge-all-private:
	PYTHONPATH=. uv run python scripts/purge_demo_data.py all --confirm "$(CONFIRM)"

privacy-check:
	PYTHONPATH=. uv run python scripts/privacy_check.py

eval:
	PYTHONPATH=. uv run python -m evals.run_eval

# Real-handwriting eval (BRESSAY). Kept out of the default `eval`/CI: it needs the
# third-party dataset and (for the VLM column) a local server. Fails loudly /
# reports unavailable rather than fabricating a number. See docs/EVAL_BRESSAY.md.
eval-bressay:
	PYTHONPATH=. uv run python -m evals.eval_htr_bressay --n $(N)

# Instrumented eval on the real curated sheets (EVAL_PROTOCOL): one run = (reader, dpi).
# Detailed (PII) JSON -> private/audit/; whitelisted public summary -> docs/.
eval-real:
	PYTHONPATH=. uv run python -m evals.eval_extraction_real --vision $(VISION) --dpi $(DPI) --n $(REAL_N)
