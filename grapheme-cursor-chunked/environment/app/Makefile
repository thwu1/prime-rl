
UNICODE_VERSION = 17.0.0
UNICODE_BASE = https://www.unicode.org/Public/$(UNICODE_VERSION)/ucd
DATA_DIR = /app/data

.PHONY: test check-data download-data validate clean

test:
	cd /app && python3 -m pytest /tests/test_state.py -v --tb=short

check-data:
	@echo "=== Unicode data file status ==="
	@for f in GraphemeBreakProperty.txt emoji-data.txt GraphemeBreakTest.txt; do \
		if [ -f $(DATA_DIR)/$$f ]; then \
			lines=$$(wc -l < $(DATA_DIR)/$$f); \
			echo "  $$f: $$lines lines"; \
		else \
			echo "  $$f: MISSING"; \
		fi; \
	done

download-data:
	@mkdir -p $(DATA_DIR)
	curl -fsSL -o $(DATA_DIR)/GraphemeBreakProperty.txt \
		$(UNICODE_BASE)/auxiliary/GraphemeBreakProperty.txt
	curl -fsSL -o $(DATA_DIR)/emoji-data.txt \
		$(UNICODE_BASE)/emoji-data.txt
	curl -fsSL -o $(DATA_DIR)/GraphemeBreakTest.txt \
		$(UNICODE_BASE)/auxiliary/GraphemeBreakTest.txt

validate:
	python3 /app/scripts/validate_tables.py

clean:
	find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
