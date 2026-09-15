.PHONY: run validate evaluate clean

run:
	python3 /app/engine/main.py

validate: run
	jq -e 'to_entries | all(.value | type == "array" and length > 0 and all(.[]; has("doc_id") and has("score") and has("title")))' /app/output.json > /dev/null
	@echo "Output validation passed"

evaluate: run
	python3 /app/evaluation/evaluate.py

clean:
	rm -f /app/output.json
