
.PHONY: validate test pipeline report

validate:
	python3 /app/validate.py

test:
	python3 -m pytest /tests/test_state.py -v

pipeline:
	bash /app/pipeline.sh

report:
	@sqlite3 -header -column /app/results.db \
		"SELECT tc.name AS test_name, pr.status FROM pipeline_results pr JOIN test_cases tc ON pr.test_case_id = tc.id ORDER BY tc.id;"
	@echo ""
	@sqlite3 /app/results.db \
		"SELECT status, COUNT(*) AS count FROM pipeline_results GROUP BY status;"
