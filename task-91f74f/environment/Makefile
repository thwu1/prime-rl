# HN-Onc-Eval-2026 Evaluation Pipeline
# Orchestrates data ingestion, evaluation, and output validation.

.PHONY: all ingest evaluate validate clean

all: evaluate ingest validate

ingest:
	@echo "Ingesting survival predictions from NDJSON..."
	@for team in alpha beta gamma delta; do \
		jq -r --arg t "$$team" \
			'[$$t, .patient_id, .event_time, .event_observed, (.risk_score | tostring)] | @tsv' \
			/app/raw_predictions/$${team}_survival.jsonl \
			> /tmp/$${team}_survival.tsv; \
		sqlite3 /app/submissions.db \
			".mode csv" \
			".import /tmp/$${team}_survival.tsv survival"; \
	done
	@echo "Ingestion complete."

evaluate:
	python3 /app/evaluate.py

validate:
	@echo "Validating outputs..."
	@test -f /app/results.json && test -f /app/stability.json \
		&& echo "Output files exist. Validation passed." \
		|| echo "VALIDATION FAILED: missing output files."

clean:
	rm -f /app/results.json /app/stability.json /tmp/*_survival.*
	sqlite3 /app/submissions.db "DELETE FROM survival;"
