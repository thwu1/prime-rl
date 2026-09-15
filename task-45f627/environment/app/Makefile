.PHONY: all validate-input analyze visualize validate-output clean

all: validate-input analyze visualize validate-output

validate-input:
	@echo "Validating input plans..."
	@for f in plans/*.json; do jq empty "$$f" || { echo "FAIL: $$f is not valid JSON"; exit 1; }; done
	@for f in plans/*.json; do jq -e '.plan_name and .state_ttl_seconds and .nodes' "$$f" > /dev/null || { echo "FAIL: $$f missing required fields"; exit 1; }; done
	@echo "All input plans validated."

analyze:
	python3 run_optimizer.py

visualize:
	@echo "Rendering DOT files to SVG..."
	@for f in output/*.dot; do dot -Tsvg "$$f" -o "$${f%.dot}.svg" || { echo "FAIL: could not render $$f"; exit 1; }; done
	@echo "All visualizations rendered."

validate-output:
	@test -f output/report.json || { echo "FAIL: output/report.json not found"; exit 1; }
	@jq empty output/report.json || { echo "FAIL: output/report.json is not valid JSON"; exit 1; }
	@jq -e '.plans | length > 0' output/report.json > /dev/null || { echo "FAIL: report has no plans"; exit 1; }
	check-jsonschema --schemafile output_schema.json output/report.json
	@echo "Output report validated against schema."

clean:
	rm -rf output/
