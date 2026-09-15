MAKEFLAGS += --no-print-directory

.PHONY: check-grammar analyze analyze-all clean

check-grammar:
	@python3 -c "from lark import Lark; Lark(open('/app/grammar.lark').read()); print('Grammar: OK')"

analyze:
ifndef PROG
	$(error PROG not set. Usage: make analyze PROG=programs/basic.lang)
endif
	@python3 /app/analyzer.py $(PROG)

analyze-all:
	@for prog in /app/programs/*.lang; do \
		echo "=== $$(basename $$prog) ==="; \
		python3 /app/analyzer.py "$$prog"; \
		echo; \
	done

clean:
	@find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
