# Makefile — Definition-of-Done task runner for security-shift-intake.
# Recipes are kept to single, portable commands so they run under both POSIX sh
# (CI / Linux) and Windows cmd. Real targets land milestone by milestone; not-yet
# -implemented targets fail loudly so a DoD is never silently "green".

.DEFAULT_GOAL := help

# Config the real-file demo runs against. V1 supports occurrence-table sheets only.
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

# Release-safety identity is intentionally not overridable from the command line.
override SAFETY_DATASET := bench-balanced
override SAFETY_SPLIT := val
override SAFETY_VISION := local_ocr

.PHONY: help install lint format format-check typecheck test check audit-deps \
        validate-config gen-data gen-pdfs gen-sheets gen-safety-sheets demo-pipeline \
        demo demo-pipeline-mock serve eval-bressay eval-real eval-synthetic eval-safety \
        purge-demo-data purge-real-data purge-all-private privacy-check

help:
	@echo security-shift-intake - available targets:
	@echo   make install         - sync the virtualenv from uv.lock
	@echo   make lint            - ruff lint
	@echo   make format          - ruff format (write)
	@echo   make format-check    - ruff format (check only)
	@echo   make typecheck       - mypy on src/data/scripts/evals
	@echo   make test            - pytest
	@echo   make check           - format-check + lint + typecheck + test
	@echo   make audit-deps      - fail on known vulnerabilities in the locked environment
	@echo   make validate-config - [M1] validate configs against the schema
	@echo   make gen-data        - [M2] generate Tier A synthetic records
	@echo   make gen-pdfs        - [M3] render Tier B handwritten PDFs
	@echo   make gen-sheets      - [tier_c] generate occurrence-table sheets, DATASET=smoke/bench-balanced/bench-operational/stress
	@echo   make gen-safety-sheets - generate the exact bench-balanced/val release corpus
	@echo   make demo-pipeline   - local zero-cost end-to-end on a real FILE=... (OCR+rules, CONFIG=...)
	@echo   make demo            - one-command synthetic showcase (real local Tesseract + review UI)
	@echo   make demo-pipeline-mock - public synthetic demo (no file, no API)
	@echo   make purge-demo-data - remove active demo artifacts (DB+sidecars, audit/, page_images/, debug/)
	@echo   make purge-real-data - remove real-sheet entries (private/reais/), needs CONFIRM=YES
	@echo   make purge-all-private - remove active entries under private/, needs CONFIRM=YES
	@echo   make privacy-check   - verify no real data/PII tracked or outside private/
	@echo   make eval-bressay    - [v2] real BR-PT handwriting eval (BRESSAY); see docs/EVAL_BRESSAY.md
	@echo   make eval-real       - instrumented real-sheet eval, VISION=local_ocr/local_vlm/mock DPI=150; see docs/EVAL_PROTOCOL.md
	@echo   make eval-synthetic  - [tier_c] synthetic-sheet eval, VISION=... DPI=... REAL_N=... SPLIT=val/test; see docs/DATASET_CONTRACT.md
	@echo   make eval-safety     - [SSI-1010] structural-safety gates on val (exit 1 if unsafe); OUT=... redirects artifacts
	@echo   "  (reader: set INTAKE_VISION=local_vlm to use the local open VLM instead of Tesseract)"

install:
	uv sync --locked

lint:
	uv run --locked ruff check .

format:
	uv run --locked ruff format .

format-check:
	uv run --locked ruff format --check .

typecheck:
	uv run --locked mypy src data scripts evals

test:
	uv run --locked pytest

# Convenience aggregate matching the M0 Definition of Done.
check: format-check lint typecheck test

audit-deps:
	uv run --locked pip-audit --local --strict --progress-spinner off

# --- Not implemented yet: fail loudly until the owning milestone lands. ---

validate-config:
	uv run --locked python -m scripts.validate_config configs/controle_ocorrencias.yaml

gen-data:
	uv run --locked python -m scripts.gen_data

gen-pdfs:
	uv run --locked python -m scripts.gen_pdfs

gen-sheets:
	uv run --locked python -m scripts.gen_sheets --dataset $(DATASET)

gen-safety-sheets:
	uv run --locked python -m scripts.gen_sheets --dataset $(SAFETY_DATASET)

demo-pipeline:
	uv run --locked python -m scripts.demo_pipeline --file "$(FILE)" --config "$(CONFIG)"

# Portfolio showcase: committed synthetic sheet -> real local Tesseract -> loopback UI.
demo:
	uv run --locked python -m scripts.showcase_demo $(DEMO_ARGS)

demo-pipeline-mock:
	uv run --locked python -m scripts.demo_pipeline_mock

# Launcher oficial da UI de revisão — recusa bind fora de loopback (sem auth + PII).
serve:
	uv run --locked python -m scripts.serve $(SERVE_ARGS)

purge-demo-data:
	uv run --locked python -m scripts.purge_demo_data demo

purge-real-data:
	uv run --locked python -m scripts.purge_demo_data real --confirm "$(CONFIRM)"

purge-all-private:
	uv run --locked python -m scripts.purge_demo_data all --confirm "$(CONFIRM)"

privacy-check:
	uv run --locked python -m scripts.privacy_check

# Real-handwriting eval (BRESSAY). Kept out of the default `eval`/CI: it needs the
# third-party dataset and (for the VLM column) a local server. Fails loudly /
# reports unavailable rather than fabricating a number. See docs/EVAL_BRESSAY.md.
eval-bressay:
	uv run --locked python -m evals.eval_htr_bressay --n $(N)

# Instrumented eval on real curated sheets (EVAL_PROTOCOL): one run = (reader, dpi).
# Detailed and allowlisted outputs stay in private/audit/; docs/ history is write-protected.
eval-real:
	uv run --locked python -m evals.eval_extraction_real --vision $(VISION) --dpi $(DPI) --n $(REAL_N)

# Tier C synthetic eval (DATASET_CONTRACT): same protocol formulas, generated truth.
eval-synthetic:
	uv run --locked python -m evals.eval_extraction_synthetic --vision $(VISION) --dpi $(DPI) --n $(REAL_N) --dataset $(DATASET) --split $(SPLIT)

# Structural-safety gate (SSI-1010): proves the core promise on val — nothing wrong
# EXITS unnoticed. Binary gates: exit 1 on unsafe_clean>0, safe_review_recall<1.0 or
# false_incident_unreviewed>0 (false_incident is REPORTED reader noise, always
# must_review, never blocking). Output goes OUTSIDE
# the repo's frozen docs/ artifacts (OUT default lives under gitignored private/).
OUT ?= private/audit/eval_safety
eval-safety:
	uv run --locked python -m evals.eval_extraction_synthetic --vision $(SAFETY_VISION) --dpi $(DPI) --dataset $(SAFETY_DATASET) --split $(SAFETY_SPLIT) --output-dir "$(OUT)" --require-safety-gates
