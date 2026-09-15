# TAC IR Optimization Pipeline

PROGRAMS := prog1 prog2 prog3 prog4 prog5 prog6
IR_DIR := programs
OUT_DIR := output
CFG_DIR := cfg

INTERP := python3 /app/ir_interpreter.py
OPT := python3 /app/optimize.py

.PHONY: all optimize verify cfg report clean

all: optimize verify cfg report

optimize:
	@mkdir -p $(OUT_DIR)
	@for p in $(PROGRAMS); do \
		$(OPT) $(IR_DIR)/$$p.ir > $(OUT_DIR)/$$p.ir; \
	done

verify: optimize
	@for p in $(PROGRAMS); do \
		$(INTERP) $(IR_DIR)/$$p.ir > /tmp/_orig_$$p.out 2>&1; \
		$(INTERP) $(OUT_DIR)/$$p.ir > /tmp/_opt_$$p.out 2>&1; \
		if ! diff -q /tmp/_orig_$$p.out /tmp/_opt_$$p.out > /dev/null; then \
			echo "FAIL: $$p output differs after optimization"; exit 1; \
		fi; \
	done
	@echo "All programs verified."

cfg:
	@mkdir -p $(CFG_DIR)
	@for p in $(PROGRAMS); do \
		$(OPT) --dot $(IR_DIR)/$$p.ir > $(CFG_DIR)/$$p.dot; \
		dot -Tsvg $(CFG_DIR)/$$p.dot -o $(CFG_DIR)/$$p.svg; \
	done

report: optimize
	@mkdir -p $(OUT_DIR)
	@echo "=== Optimization Report ===" > $(OUT_DIR)/report.txt
	@for p in $(PROGRAMS); do \
		orig=$$(wc -l < $(IR_DIR)/$$p.ir); \
		opt=$$(wc -l < $(OUT_DIR)/$$p.ir); \
		saved=$$(( orig - opt )); \
		echo "$$p: $$orig -> $$opt lines ($$saved removed)" >> $(OUT_DIR)/report.txt; \
	done

clean:
	rm -rf $(OUT_DIR) $(CFG_DIR)
