PROOFS := $(wildcard proofs/*.json)

.PHONY: all test validate report graph obligations clean

all: test validate report graph obligations

test:
	python3 -m pytest proof_engine/test_integration.py -v --tb=short

validate:
	@set -e; for f in $(PROOFS); do \
		echo "Validating $$f..."; \
		python3 validate_proof.py "$$f" > /dev/null; \
	done; echo "All proof structures validated."

report:
	@mkdir -p reports
	@(for f in $(PROOFS); do \
		python3 validate_proof.py "$$f"; \
	done) | jq -s '{total_files: length, valid_count: [.[] | select(.valid)] | length, invalid_count: [.[] | select(.valid | not)] | length, files: [.[] | {file: .file, valid: .valid}]}' > reports/summary.json
	@echo "Report written to reports/summary.json"

graph:
	@mkdir -p graphs
	@set -e; for f in $(PROOFS); do \
		base=$$(basename "$$f" .json); \
		python3 validate_proof.py --format dot "$$f" > "graphs/$${base}.dot"; \
		dot -Tsvg "graphs/$${base}.dot" -o "graphs/$${base}.svg"; \
	done
	@echo "Graphs written to graphs/"

obligations:
	@mkdir -p obligations
	@set -e; for f in $(PROOFS); do \
		base=$$(basename "$$f" .json); \
		python3 validate_proof.py --format obligations "$$f" > "obligations/$${base}.json"; \
	done
	@echo "Obligations written to obligations/"

clean:
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
	rm -rf reports/ graphs/ obligations/
