PYTHON ?= python3.11
SRC_DIR := src
PKG_DIR := src/logminer
TEST_DIR := tests

.PHONY: install lint typecheck test ci clean

install:
	$(PYTHON) -m pip install -e . -q

lint:
	$(PYTHON) -m ruff check $(SRC_DIR)/

typecheck:
	$(PYTHON) -m mypy --config-file=setup.cfg $(PKG_DIR)/

test:
	$(PYTHON) -m pytest $(TEST_DIR)/ -v --tb=short

ci: install lint typecheck test
	@echo "All CI stages passed."

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
