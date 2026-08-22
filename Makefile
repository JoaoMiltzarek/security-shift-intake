# Project tasks use portable commands that run under POSIX sh and Windows cmd.

.DEFAULT_GOAL := help

# Config the real-file demo runs against. V1 supports occurrence-table sheets only.
CONFIG ?= configs/controle_ocorrencias.yaml

# Optional arguments for the one-command synthetic showcase (e.g. --no-open).
DEMO_ARGS ?=

# Loopback UI port. Override with `make serve PORT=8080`.
PORT ?= 8000

# Synthetic evaluation reader, rasterization DPI, and optional sample cap.
READER ?= local_ocr
DPI ?= 150
REAL_N ?= 0

# Tier C canonical dataset name (docs/DATASET_CONTRACT.md par.4). Override:
# `make gen-sheets DATASET=bench-balanced`.
DATASET ?= smoke

# Synthetic eval split: validation is the default; test remains held out.
SPLIT ?= val

# Release-safety identity is intentionally not overridable from the command line.
override SAFETY_DATASET := bench-balanced
override SAFETY_SPLIT := val
override SAFETY_READER := local_ocr

.PHONY: help install check-test-env lint format format-check typecheck test check audit-deps \
        validate-config gen-sheets gen-safety-sheets demo-pipeline \
        demo demo-pipeline-mock serve eval-synthetic eval-safety \
        purge-demo-data purge-real-data purge-all-private privacy-check

help:
	@echo security-shift-intake - available targets:
	@echo   make install         - sync the virtualenv from uv.lock
	@echo   make check-test-env  - verify an exact sync and the Starlette test backend
	@echo   make lint            - ruff lint
	@echo   make format          - ruff format (write)
	@echo   make format-check    - ruff format (check only)
	@echo   make typecheck       - mypy on src/data/scripts/evals
	@echo   make test            - pytest
	@echo   make check           - format-check + lint + typecheck + test
	@echo   make audit-deps      - fail on known vulnerabilities in the locked environment
	@echo   make validate-config - validate configs against the schema
	@echo   make gen-sheets      - generate occurrence-table sheets, DATASET=smoke/bench-balanced/bench-operational/stress
	@echo   make gen-safety-sheets - generate the exact bench-balanced/val release corpus
	@echo   make demo-pipeline   - local zero-cost end-to-end on a real FILE=... (OCR+rules, CONFIG=...)
	@echo   make demo            - one-command synthetic showcase (real local Tesseract + review UI)
	@echo   make demo-pipeline-mock - public synthetic demo (no file, no API)
	@echo   make purge-demo-data - remove active demo artifacts (DB+sidecars, audit/, page_images/, debug/)
	@echo   make purge-real-data - remove real-sheet entries (private/reais/), needs CONFIRM=YES
	@echo   make purge-all-private - remove active entries under private/, needs CONFIRM=YES
	@echo   make privacy-check   - verify no real data/PII tracked or outside private/
	@echo   make eval-synthetic  - synthetic-sheet eval, READER=... DPI=... REAL_N=... SPLIT=val/test
	@echo   make eval-safety     - structural-safety gates on val; OUT=... redirects artifacts

install:
	uv sync --locked

check-test-env:
	uv sync --locked --check
	uv run --locked --no-sync python -m scripts.check_test_environment

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

# Local quality aggregate used by contributors.
check: format-check lint typecheck test

audit-deps:
	uv run --locked python -m scripts.audit_locked_dependencies

validate-config:
	uv run --locked python -m scripts.validate_config configs/controle_ocorrencias.yaml

gen-sheets:
	uv run --locked python -m scripts.gen_sheets --dataset $(DATASET)

gen-safety-sheets:
	uv run --locked python -m scripts.gen_sheets --dataset $(SAFETY_DATASET)

demo-pipeline:
	uv run --locked python -m scripts.demo_pipeline --file "$(FILE)" --config "$(CONFIG)"

# Committed synthetic sheet -> local Tesseract -> loopback review UI.
demo:
	uv run --locked python -m scripts.showcase_demo $(DEMO_ARGS)

demo-pipeline-mock:
	uv run --locked python -m scripts.demo_pipeline_mock

# The review UI refuses non-loopback binds because v1 has no authentication.
serve:
	uv run --locked python -m scripts.serve --port "$(PORT)" $(SERVE_ARGS)

purge-demo-data:
	uv run --locked python -m scripts.purge_demo_data demo

purge-real-data:
	uv run --locked python -m scripts.purge_demo_data real --confirm "$(CONFIRM)"

purge-all-private:
	uv run --locked python -m scripts.purge_demo_data all --confirm "$(CONFIRM)"

privacy-check:
	uv run --locked python -m scripts.privacy_check

# Synthetic evaluation uses generated ground truth.
eval-synthetic:
	uv run --locked python -m evals.eval_extraction_synthetic --vision $(READER) --dpi $(DPI) --n $(REAL_N) --dataset $(DATASET) --split $(SPLIT)

# The release gate fails when unsafe output escapes review. Detailed output defaults
# to private storage so frozen public evidence is never overwritten by a local run.
OUT ?= private/audit/eval_safety
eval-safety:
	uv run --locked python -m evals.eval_extraction_synthetic --vision $(SAFETY_READER) --dpi $(DPI) --dataset $(SAFETY_DATASET) --split $(SAFETY_SPLIT) --output-dir "$(OUT)" --require-safety-gates
