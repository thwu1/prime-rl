PYTHON = python3
PIPELINE = /app/pipeline.py
OUTPUT = /app/output
CODEBASE = /app/codebase

.PHONY: all extract resolve graph store analyze clean

all: extract resolve graph store analyze

extract:
	mkdir -p $(OUTPUT)
	$(PYTHON) $(PIPELINE) extract $(CODEBASE) $(OUTPUT)/raw_imports.json

resolve: extract
	$(PYTHON) $(PIPELINE) resolve $(CODEBASE) $(OUTPUT)/raw_imports.json $(OUTPUT)/resolved_deps.json

graph: resolve
	$(PYTHON) $(PIPELINE) graph $(OUTPUT)/resolved_deps.json $(OUTPUT)/deps.dot
	dot -Tsvg $(OUTPUT)/deps.dot -o $(OUTPUT)/deps.svg

store: resolve
	$(PYTHON) $(PIPELINE) store $(CODEBASE) $(OUTPUT)/resolved_deps.json $(OUTPUT)/analysis.db

analyze: resolve
	$(PYTHON) $(PIPELINE) analyze $(CODEBASE) $(OUTPUT)/resolved_deps.json $(OUTPUT)/analysis.json

clean:
	rm -rf $(OUTPUT)/*
