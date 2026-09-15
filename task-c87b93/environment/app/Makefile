.PHONY: test lint clean check

test:
	@echo "Running test suite..."
	@cd /app && python3 -m pytest /tests/test_state.py -v 2>&1; echo "Exit: $$?"

lint:
	@python3 -m py_compile cascade.py dom.py tokenizer.py parser.py specificity.py matcher.py resolver.py && echo "All modules compile OK"

clean:
	@find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
	@find /app -name "*.pyc" -delete 2>/dev/null; true

check:
	@python3 -c "from cascade import main; print('Module imports OK')"
	@echo "Modules: dom.py tokenizer.py parser.py specificity.py matcher.py resolver.py cascade.py"
