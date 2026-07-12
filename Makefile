# Makefile — Definition-of-Done task runner for security-shift-intake.
# Recipes are kept to single, portable commands so they run under both POSIX sh
# (CI / Linux) and Windows cmd. Real targets land milestone by milestone; not-yet
# -implemented targets fail loudly so a DoD is never silently "green".

.DEFAULT_GOAL := help

# Config the real-file demo runs against. Defaults to the v1 occurrence-table sheet;
# override e.g. `make demo-pipeline FILE=... CONFIG=configs/htmicron_security.yaml`.
CONFIG ?= configs/controle_ocorrencias.yaml

# Optional arguments for the one-command synthetic showcase (e.g. --no-open).
DEMO_ARGS ?=

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

# Tier C synthetic eval split (contract par.5: val=default anti-tuning; test=milestone).
SPLIT ?= val

# Watch-dir for make watch (override: make watch WATCH_DIR=private/inbox).
WATCH_DIR ?= private/inbox

.PHONY: help install lint format format-check typecheck test check \
        validate-config gen-data gen-pdfs gen-sheets demo-transcribe demo-pipeline \
        demo demo-pipeline-mock serve eval eval-bressay eval-real eval-synthetic eval-safety watch \
        purge-demo-data purge-real-data purge-all-private privacy-check

help:
	@echo security-shift-intake - available targets:
	@echo   make install         - sync the virtualenv from uv.lock
	@echo   make lint            - ruff lint
	@echo   make format          - ruff format (write)
	@echo   make format-check    - ruff format (check only)
	@echo   make typecheck       - mypy on src/data/scripts/evals
	@echo   make test            - pytest
	@echo   make check           - lint + typecheck + test (the M0 DoD)
	@echo   make validate-config - [M1] validate configs against the schema
	@echo   make gen-data        - [M2] generate Tier A synthetic records
	@echo   make gen-pdfs        - [M3] render Tier B handwritten PDFs
	@echo   make gen-sheets      - [tier_c] generate occurrence-table sheets, DATASET=smoke/bench-balanced/bench-operational/stress
	@echo   make demo-transcribe - [M4] run the real VLM on one PDF (needs API key)
	@echo   make demo-pipeline   - local zero-cost end-to-end on a real FILE=... (OCR+rules, CONFIG=...)
	@echo   make demo            - one-command synthetic showcase (real local Tesseract + review UI)
	@echo   make demo-pipeline-mock - public synthetic demo (no file, no API)
	@echo   make purge-demo-data - wipe temp demo artifacts (DB+sidecars, audit/, page_images/, debug/)
	@echo   make purge-real-data - wipe real sheets (private/reais/), needs CONFIRM=YES
	@echo   make purge-all-private - wipe ALL of private/ (incl. curadoria), needs CONFIRM=YES
	@echo   make privacy-check   - verify no real data/PII tracked or outside private/
	@echo   make eval            - [M8] produce metrics.json + EVAL_REPORT.md
	@echo   make eval-bressay    - [v2] real BR-PT handwriting eval (BRESSAY); see docs/EVAL_BRESSAY.md
	@echo   make eval-real       - instrumented real-sheet eval, VISION=local_ocr/local_vlm/mock DPI=150; see docs/EVAL_PROTOCOL.md
	@echo   make eval-synthetic  - [tier_c] synthetic-sheet eval, VISION=... DPI=... REAL_N=... SPLIT=val/test; see docs/DATASET_CONTRACT.md
	@echo   make eval-safety     - [SSI-1010] structural-safety gates on val (exit 1 if unsafe); OUT=... redirects artifacts
	@echo   "  (reader: set INTAKE_VISION=local_vlm to use the local open VLM instead of Tesseract)"
	@echo   make watch           - poll WATCH_DIR for new PDFs; writes drafts, NEVER sends email \(Ctrl-C to stop\)

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src data scripts evals

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

# Portfolio showcase: committed synthetic sheet -> real local Tesseract -> loopback UI.
demo:
	uv run python -m scripts.showcase_demo $(DEMO_ARGS)

demo-pipeline-mock:
	PYTHONPATH=. uv run python scripts/demo_pipeline_mock.py

# Launcher oficial da UI de revisão — recusa bind fora de loopback (sem auth + PII).
serve:
	PYTHONPATH=. uv run python scripts/serve.py $(SERVE_ARGS)

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

# Tier C synthetic eval (DATASET_CONTRACT): same protocol formulas, generated truth.
eval-synthetic:
	PYTHONPATH=. uv run python -m evals.eval_extraction_synthetic --vision $(VISION) --dpi $(DPI) --n $(REAL_N) --split $(SPLIT)

# Structural-safety gate (SSI-1010): proves the core promise on val — nothing wrong
# EXITS unnoticed. Binary gates: exit 1 on unsafe_clean>0, safe_review_recall<1.0 or
# false_incident_unreviewed>0 (false_incident is REPORTED reader noise, always
# must_review, never blocking). Output goes OUTSIDE
# the repo's frozen docs/ artifacts (OUT default lives under gitignored private/).
OUT ?= private/audit/eval_safety
eval-safety:
	PYTHONPATH=. uv run python -m evals.eval_extraction_synthetic --vision $(VISION) --dpi $(DPI) --split $(SPLIT) --output-dir $(OUT) --require-safety-gates

# Intake Watch — idempotent PDF watcher. Creates drafts in WATCH_DIR/drafts/.
# NEVER sends email. Ctrl-C to stop. Override: make watch WATCH_DIR=private/inbox.
watch:
	PYTHONPATH=. uv run python scripts/run_watch.py --watch-dir $(WATCH_DIR)
