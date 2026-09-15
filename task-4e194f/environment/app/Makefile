# IR Optimization Pipeline
# Complete each target below.

PYTHON := python3
PROGRAMS := prog1 prog2 prog3 prog4 prog5
PROGS_DIR := programs

.PHONY: all optimize-all verify report clean

all: optimize-all verify report

optimize-all:
	@echo "TODO: run optimizer on each program, producing $(PROGS_DIR)/<name>.opt.ir"

verify:
	@echo "TODO: compare interpreter output of original vs optimized using diff"

report:
	@echo "TODO: generate optimization_report.json using jq"

clean:
	rm -f $(PROGS_DIR)/*.opt.ir optimization_report.json
