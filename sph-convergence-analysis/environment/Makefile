.PHONY: validate analyze check clean

DATA_DIR = /app/data

validate:
	@echo "Validating XML data integrity..."
	@find $(DATA_DIR) -name "*.xml" | xargs xmlstarlet val -w
	@echo "XML validation passed"

analyze: validate
	python3 /app/sph_regression.py

check: analyze
	@test -f /app/results.json || (echo "ERROR: results.json not generated" && exit 1)
	@python3 -c "import json; json.load(open('/app/results.json'))" 2>/dev/null || (echo "ERROR: invalid JSON" && exit 1)
	@echo "Quality assessment complete"

clean:
	rm -f /app/results.json
