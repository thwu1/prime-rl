.PHONY: all analyze graphs validate clean

PROGS := $(wildcard /app/programs/*.json)

all: analyze graphs validate

analyze:
	@mkdir -p /app/results /app/graphs
	python3 /app/analyzer.py $(PROGS)

graphs: analyze
	@for f in /app/graphs/*.dot; do \
		dot -Tsvg "$$f" -o "$${f%.dot}.svg"; \
	done

validate: analyze
	@echo "Validating output JSON..."
	@for f in /app/results/*.json; do \
		jq -e '.name and .work and .span and .ideal_parallelism and .data_races' "$$f" > /dev/null || (echo "FAIL: $$f" && exit 1); \
	done
	@echo "All outputs valid."

clean:
	rm -rf /app/results /app/graphs
