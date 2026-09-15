# VLIW Optimizer Build and Verification Pipeline
#
# Usage:
#   make build         Compile the C bundle validator
#   make verify-all    Full pipeline: optimize -> validate -> simulate -> compare
#   make trace PROG=x  Execution trace for debugging a specific program
#   make clean         Remove build artifacts
#   make help          Show this help

CC = gcc
CFLAGS = -O2 -Wall -Wextra

PROGRAMS = basic_arith hash_compute poly_batch tree_walk matmul_2x2

.PHONY: all build verify-all trace clean help

all: build

build: bundle_check

bundle_check: bundle_check.c
	$(CC) $(CFLAGS) -o $@ $<

verify-all: build
	@ok=0; fail=0; \
	for p in $(PROGRAMS); do \
		printf "  %-16s " "$$p"; \
		python3 optimizer.py $$p > /tmp/$$p.vliw 2>/dev/null && \
		./bundle_check /tmp/$$p.vliw > /dev/null 2>&1 && \
		python3 machine.py compare /tmp/$$p.vliw $$p > /dev/null 2>&1; \
		if [ $$? -eq 0 ]; then \
			echo "[PASS]"; ok=$$((ok+1)); \
		else \
			echo "[FAIL]"; fail=$$((fail+1)); \
		fi; \
	done; \
	echo ""; \
	echo "Results: $$ok passed, $$fail failed"; \
	test $$fail -eq 0

trace: build
	@if [ -z "$(PROG)" ]; then \
		echo "Usage: make trace PROG=<program_name>"; \
		echo "Programs: $(PROGRAMS)"; \
		exit 1; \
	fi
	python3 optimizer.py $(PROG) > /tmp/$(PROG).vliw
	@echo "=== Bundle Validation ==="
	./bundle_check /tmp/$(PROG).vliw --verbose
	@echo ""
	@echo "=== Execution Trace ==="
	python3 machine.py simulate /tmp/$(PROG).vliw --init $(PROG) --trace

clean:
	rm -f bundle_check /tmp/*.vliw

help:
	@echo "Targets:"
	@echo "  build       - Compile bundle_check from bundle_check.c"
	@echo "  verify-all  - Run full verification pipeline for all programs"
	@echo "  trace       - Execution trace (usage: make trace PROG=basic_arith)"
	@echo "  clean       - Remove build artifacts"
	@echo ""
	@echo "Programs: $(PROGRAMS)"
