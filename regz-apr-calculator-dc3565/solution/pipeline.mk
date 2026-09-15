.PHONY: all compute enrich store report clean

BUILD := /app/build

all: report

$(BUILD):
	mkdir -p $(BUILD)

compute: | $(BUILD)
	for loan in /app/loans/*.json; do /app/regz_apr "$$loan"; done > $(BUILD)/apr_results.ndjson

enrich: compute
	python3 /app/enrich.py

store: enrich
	rm -f /app/results.db
	sqlite3 /app/results.db < /app/schema.sql
	python3 /app/import_db.py

report: store
	/app/report.sh > $(BUILD)/summary.json

clean:
	rm -rf $(BUILD) /app/results.db
