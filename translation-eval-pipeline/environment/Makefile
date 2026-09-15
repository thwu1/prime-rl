RESULTS = results.json
SCHEMA = output_schema.json
CONFIG = pipeline_config.json

.PHONY: evaluate validate clean

evaluate:
	python3 -m pipeline.main

validate: $(RESULTS)
	@python3 -c "import json, sys; \
	schema = json.load(open('$(SCHEMA)')); \
	data = json.load(open('$(RESULTS)')); \
	missing = [k for k in schema.get('required', []) if k not in data]; \
	print('PASS: all required sections present') if not missing else (print('FAIL: missing ' + str(missing)), sys.exit(1))"

clean:
	rm -f $(RESULTS)
