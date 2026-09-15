
MANIFEST ?= /app/data/manifest.json
OUTPUT_DIR ?= /app/output

.PHONY: all taxonomy-db metrics validate

all: taxonomy-db metrics validate

taxonomy-db: $(OUTPUT_DIR)/taxonomy.db

$(OUTPUT_DIR)/taxonomy.db:
	@mkdir -p $(OUTPUT_DIR)
	python3 /app/pipeline.py taxonomy $(MANIFEST) $(OUTPUT_DIR)

metrics: $(OUTPUT_DIR)/results.tsv

$(OUTPUT_DIR)/results.tsv $(OUTPUT_DIR)/rankings.tsv &: $(OUTPUT_DIR)/taxonomy.db
	python3 /app/pipeline.py metrics $(MANIFEST) $(OUTPUT_DIR)

validate: $(OUTPUT_DIR)/validation.json

$(OUTPUT_DIR)/validation.json: $(OUTPUT_DIR)/taxonomy.db
	python3 /app/pipeline.py validate $(MANIFEST) $(OUTPUT_DIR)
