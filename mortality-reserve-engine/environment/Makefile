# Actuarial valuation pipeline
# Validates XML data, loads into SQLite, computes reserves

DB_PATH := /app/mortality.db
DATA_DIR := /app/data
CONFIG := /app/config.json
SCHEMA := /app/schema.sql
RESULTS := /app/results.json

XML_FILES := $(wildcard $(DATA_DIR)/*.xml)

.PHONY: pipeline clean validate load compute

pipeline: validate compute

validate:
	@echo "=== Validating XML files ==="
	@for f in $(XML_FILES); do \
		xmllint --noout $f 2>/dev/null && echo "  OK: $f" || echo "  WARN: $f"; \
	done

load: validate
	@echo "=== Loading data into SQLite ==="
	rm -f $(DB_PATH)
	sqlite3 $(DB_PATH) < $(SCHEMA)
	python3 /app/load_data.py --db $(DB_PATH) --data-dir $(DATA_DIR)

compute:
	@echo "=== Computing reserves ==="
	python3 /app/compute_reserves.py --db $(DB_PATH) --config $(CONFIG) --output $(RESULTS)

clean:
	rm -f $(DB_PATH) $(RESULTS)
