.PHONY: test check-grammar clean

PYTHON = python3

test: check-grammar
	$(PYTHON) -m pytest /tests/test_state.py -v

check-grammar:
	@$(PYTHON) -c "from lark import Lark; Lark(open('grammar.lark').read(), parser='earley', start='start'); print('Grammar OK')"

clean:
	@find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null; true
