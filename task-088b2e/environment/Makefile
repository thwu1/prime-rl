.PHONY: all validate test-oracle conformance check-reports clean

all: validate test-oracle conformance check-reports
	@echo "=== All pipeline stages passed ==="

validate:
	@echo "--- Stage 1: Validating suite and profile structure ---"
	@python3 /app/ttcn3_validate.py --suites /app/suites/ --oracle /app/oracle/ --pics /app/pics/
	@echo "--- Validation passed ---"

test-oracle:
	@echo "--- Stage 2: Running template matching and verdict oracle tests ---"
	@python3 /app/conformance_runner.py
	@echo "--- Oracle tests passed ---"

conformance:
	@echo "--- Stage 3: Running conformance engine ---"
	@python3 /app/run_conformance.py
	@echo "--- Conformance reports generated ---"

check-reports:
	@echo "--- Stage 4: Validating conformance reports ---"
	@python3 /app/ttcn3_validate.py --reports /app/
	@echo "--- Report validation passed ---"

clean:
	rm -f /app/report_*.json
