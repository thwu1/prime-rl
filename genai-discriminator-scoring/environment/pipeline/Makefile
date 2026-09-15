SHELL := /bin/bash
DB := /app/eval.db
DATA := /app/data
OUT := /app/output
PIPE := /app/pipeline

.PHONY: all clean

all: $(OUT)/rankings.json

clean:
	rm -f $(DB)
	rm -rf $(OUT)

$(DB): $(DATA)/ground_truth.json
	rm -f $@
	sqlite3 $@ < $(PIPE)/db_schema.sql
	bash $(PIPE)/ingest.sh $@ $(DATA)

$(OUT)/validation_report.json: $(DB)
	mkdir -p $(OUT)
	bash $(PIPE)/validate.sh $(DB) $(DATA) $(OUT)

$(OUT)/metrics.json: $(DB)
	mkdir -p $(OUT)
	python3 $(PIPE)/compute.py --db $(DB) --output $(OUT)

$(OUT)/rankings.json: $(OUT)/metrics.json
	mkdir -p $(OUT)
	sqlite3 $(DB) < $(PIPE)/rank.sql > $@
