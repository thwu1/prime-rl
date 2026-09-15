CC = gcc
CFLAGS = -Wall -Wextra -O2

.PHONY: all generate check analyze clean

all: generate

tools/gen_stress_ir: tools/gen_stress_ir.c
	$(CC) $(CFLAGS) -o $@ $<

programs/spill_cascade.json: tools/gen_stress_ir
	./tools/gen_stress_ir spill_cascade > $@

programs/nested_loop_pressure.json: tools/gen_stress_ir
	./tools/gen_stress_ir nested_loop_pressure > $@

generate: programs/spill_cascade.json programs/nested_loop_pressure.json

check: allocator.py
	@for f in programs/*.json; do \
		python3 tools/check_alloc.py "$$f" || exit 1; \
	done

analyze:
	@for f in programs/*.json; do \
		blocks=$$(jq '.functions[0].blocks | length' "$$f"); \
		instrs=$$(jq '[.functions[0].blocks[].instrs[]] | length' "$$f"); \
		vregs=$$(jq '[.functions[0].blocks[].instrs[] | select(.class != null) | .dst] | unique | length' "$$f"); \
		echo "$$f: $$blocks blocks, $$instrs instrs, $$vregs vregs"; \
	done

clean:
	rm -f tools/gen_stress_ir programs/spill_cascade.json programs/nested_loop_pressure.json
