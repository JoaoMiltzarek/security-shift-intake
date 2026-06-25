# Makefile — Definition-of-Done task runner for security-shift-intake.
# Recipes are kept to single, portable commands so they run under both POSIX sh
# (CI / Linux) and Windows cmd. Real targets land milestone by milestone; not-yet
# -implemented targets fail loudly so a DoD is never silently "green".

.DEFAULT_GOAL := help

.PHONY: help install lint format format-check typecheck test check \
        validate-config gen-data gen-pdfs demo-transcribe demo-pipeline eval \
        purge-demo-data privacy-check

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
	@echo   make demo-transcribe - [M4] run the real VLM on one PDF (needs API key)
	@echo   make demo-pipeline   - [M9] local zero-cost end-to-end on FILE=... (OCR+rules)
	@echo   make purge-demo-data - [M9] wipe real data in private/ after a test
	@echo   make privacy-check   - verify no real data/PII tracked or outside private/
	@echo   make eval            - [M8] produce metrics.json + EVAL_REPORT.md

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
	PYTHONPATH=. uv run python scripts/validate_config.py configs/htmicron_security.yaml

gen-data:
	PYTHONPATH=. uv run python scripts/gen_data.py

gen-pdfs:
	PYTHONPATH=. uv run python scripts/gen_pdfs.py

demo-transcribe:
	PYTHONPATH=. uv run python scripts/demo_transcribe.py --file "$(FILE)"

demo-pipeline:
	PYTHONPATH=. uv run python scripts/demo_pipeline.py --file "$(FILE)"

purge-demo-data:
	PYTHONPATH=. uv run python scripts/purge_demo_data.py

privacy-check:
	PYTHONPATH=. uv run python scripts/privacy_check.py

eval:
	PYTHONPATH=. uv run python -m evals.run_eval
