# Pipeline orchestration — DO NOT MODIFY this file.
# Implements a three-stage data pipeline:
#   1. extract:  sqlite3 CLI → JSON
#   2. compute:  Python → JSON
#   3. rank:     jq → JSON

.PHONY: all clean

INTERMEDIATE := /app/intermediate
OUTPUT := /app/output

all: $(OUTPUT)/leaderboard.json

$(INTERMEDIATE)/extracted.json: /app/eval.db /app/pipeline/extract.sql
	@mkdir -p $(INTERMEDIATE)
	sqlite3 /app/eval.db < /app/pipeline/extract.sql > $@

$(INTERMEDIATE)/config.json: /app/config.yaml
	@mkdir -p $(INTERMEDIATE)
	python3 -c "import yaml,json,sys;print(json.dumps(yaml.safe_load(open(sys.argv[1]))))" $< > $@

$(INTERMEDIATE)/metrics.json: $(INTERMEDIATE)/extracted.json /app/config.yaml /app/pipeline/compute_metrics.py
	python3 /app/pipeline/compute_metrics.py $(INTERMEDIATE)/extracted.json /app/config.yaml > $@

$(OUTPUT)/leaderboard.json: $(INTERMEDIATE)/metrics.json $(INTERMEDIATE)/config.json /app/pipeline/rank_and_validate.jq
	@mkdir -p $(OUTPUT)
	jq --slurpfile config $(INTERMEDIATE)/config.json -f /app/pipeline/rank_and_validate.jq $(INTERMEDIATE)/metrics.json > $@

clean:
	rm -rf $(INTERMEDIATE) $(OUTPUT)
