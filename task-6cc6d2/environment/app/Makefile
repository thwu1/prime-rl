.PHONY: validate check-deps bode full-pipeline clean

validate:
	@echo "=== Running local validation ==="
	python3 tools/validate.py

check-deps:
	@echo "=== Checking for forbidden imports ==="
	@python3 -c "\
	with open('elliptic_filter.py') as f: \
	    lines = f.readlines(); \
	forbidden = ['scipy', 'mpmath']; \
	violations = [(i+1, l.strip()) for i, l in enumerate(lines) \
	    if not l.strip().startswith('#') \
	    and any(('import ' + lib) in l or ('from ' + lib) in l for lib in forbidden)]; \
	[print(f'  VIOLATION line {n}: {l}') for n, l in violations]; \
	exit(1) if violations else print('  OK: no forbidden imports found')"

bode:
	@echo "=== Generating Bode plots ==="
	python3 tools/filterspec.py pipeline --configs reference_data/ --output output/

full-pipeline: check-deps validate bode
	@echo ""
	@echo "=== Full pipeline complete ==="

clean:
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
	find . -name '*.pyc' -delete 2>/dev/null; true
	rm -rf output/
