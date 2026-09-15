# Catalytic reactor simulation pipeline
DB_FILE := /app/properties.db
SCHEMA := /app/schema.sql
BATCH_IN := /app/datasets/batch_cases.json
BATCH_OUT := /app/datasets/batch_results.json

.PHONY: init batch clean

init: $(SCHEMA)
	sqlite3 $(DB_FILE) < $(SCHEMA)

batch: $(BATCH_IN)
	bash /app/batch_run.sh $(BATCH_INPUT) $(BATCH_OUT)

clean:
	rm -f $(DB_FILE) $(BATCH_OUT)
