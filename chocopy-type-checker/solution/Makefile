SHELL := /bin/bash

# ChocoPy Type Checker Build System
PROGRAMS := $(wildcard programs/*.py)
RESULTS := $(patsubst programs/%.py,build/%.json,$(PROGRAMS))

.PHONY: typecheck-all validate diff-check clean

typecheck-all: $(RESULTS)

build:
	mkdir -p build

build/%.json: programs/%.py typechecker.py chocopy_tc | build
	python3 ./chocopy_tc "$<" --pretty > "$@" || true

validate: $(RESULTS)
	@echo "Validating JSON structure..."
	@for f in $(RESULTS); do \
		if ! jq -e 'has("well_typed") and has("globals") and has("classes") and has("errors") and (.globals | type) == "object" and (.classes | type) == "object" and (.errors | type) == "array"' "$$f" > /dev/null 2>&1; then \
			echo "FAIL: $$f"; \
			exit 1; \
		fi; \
	done
	@echo "All outputs have valid structure."

diff-check: $(RESULTS)
	@echo "Comparing against reference ASTs..."
	@fail=0; for f in $(RESULTS); do \
		ref="reference_asts/$$(basename $$f)"; \
		if [ -f "$$ref" ]; then \
			if ! diff <(jq -S . "$$f") <(jq -S . "$$ref") > /dev/null 2>&1; then \
				echo "DIFF: $$f vs $$ref"; \
				diff <(jq -S . "$$f") <(jq -S . "$$ref") || true; \
				fail=1; \
			fi; \
		else \
			echo "WARN: no reference for $$(basename $$f)"; \
		fi; \
	done; \
	if [ "$$fail" = "1" ]; then echo "FAILED"; exit 1; fi; \
	echo "All outputs match references."

clean:
	rm -rf build
