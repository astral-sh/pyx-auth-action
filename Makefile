.PHONY: all
all:
	@echo "No default target, use 'lint' or 'fix'"

.PHONY: lint
lint:
	uv run --dev ruff format --check
	uv run --dev ruff check
	uv run --dev pyright

.PHONY: fix
fix:
	uv run --dev ruff format
	uv run --dev ruff check --fix

# .PHONY: test
# test:
# 	uvx --with-requirements=action.py pytest action.py
