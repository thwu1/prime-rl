.PHONY: all build run-engine truss clean

GRAPH_ENGINE = /app/graph-engine/target/release/graph_engine
OUTPUT_DIR = /app/output

all: build run-engine truss

build:
	cd /app/graph-engine && cargo build --release 2>&1

run-engine: build
	$(GRAPH_ENGINE) /data/initial_edges.csv /data/operations.csv 300 $(OUTPUT_DIR)

truss: run-engine
	python3 /app/scripts/truss.py $(OUTPUT_DIR)/final_edges.txt $(OUTPUT_DIR)/truss_decomposition.txt

clean:
	rm -rf $(OUTPUT_DIR)/* /app/graph-engine/target
