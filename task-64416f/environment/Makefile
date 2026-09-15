# TAC IR Optimization Pipeline
# Complete all targets so that 'make all' runs the full pipeline.

PROGRAMS := prog1 prog2 prog3 prog4 prog5 prog6
IR_DIR := programs
OUT_DIR := output
CFG_DIR := cfg

INTERP := python3 /app/ir_interpreter.py
OPT := python3 /app/optimize.py

.PHONY: all optimize verify cfg report clean

# Run the full pipeline in correct dependency order
all:
	@echo "TODO: wire up all pipeline stages"

# Run optimizer on all programs, writing results to $(OUT_DIR)/
optimize:
	@echo "TODO: run optimizer on each program"

# Verify semantic equivalence between original and optimized IR
verify:
	@echo "TODO: compare interpreter outputs with diff"

# Generate DOT-format CFGs and render to SVG using dot
cfg:
	@echo "TODO: generate DOT files and render SVGs"

# Generate optimization statistics report at $(OUT_DIR)/report.txt
report:
	@echo "TODO: count lines and write report"

# Remove all generated artifacts
clean:
	rm -rf $(OUT_DIR) $(CFG_DIR)
