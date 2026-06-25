"""Project scripts package.

Marks `scripts/` as a package so modules can import siblings (e.g.
`from scripts.check_real_data import ...`) with a single, unambiguous module name
under mypy. Scripts remain runnable directly (e.g. the pre-commit guard calls
`python scripts/check_real_data.py`).
"""
