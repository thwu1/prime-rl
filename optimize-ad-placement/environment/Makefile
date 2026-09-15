# Ad Placement Optimization — Benchmarking Pipeline

SOLVER ?= /app/solver.py
DB     ?= /app/results.db

.PHONY: benchmark analyze by-type worst clean

# Run solver on all test cases, store results in SQLite, output JSON summary
benchmark:
	python3 /app/benchmark.py --solver $(SOLVER) --db $(DB) | jq .

# Show recent per-case results from the database
analyze:
	@sqlite3 -header -column $(DB) \
		"SELECT r.case_id, m.n, m.distribution_type, m.area_cv, \
		        printf('%.4f', r.score) AS score, \
		        printf('%.0f', r.runtime_ms) AS ms \
		 FROM runs r JOIN case_metadata m ON r.case_id = m.case_id \
		 ORDER BY r.run_id DESC LIMIT 20"

# Aggregate scores by distribution type
by-type:
	@sqlite3 -header -column $(DB) \
		"SELECT m.distribution_type, COUNT(*) AS cnt, \
		        printf('%.4f', AVG(r.score)) AS avg_score, \
		        printf('%.4f', MIN(r.score)) AS min_score \
		 FROM runs r JOIN case_metadata m ON r.case_id = m.case_id \
		 WHERE r.run_id IN ( \
		     SELECT MAX(run_id) FROM runs GROUP BY case_id \
		 ) \
		 GROUP BY m.distribution_type"

# Show the 5 worst-performing cases from the latest run
worst:
	@sqlite3 -header -column $(DB) \
		"SELECT r.case_id, m.distribution_type, m.area_cv, \
		        m.max_area_pct, printf('%.4f', r.score) AS score \
		 FROM runs r JOIN case_metadata m ON r.case_id = m.case_id \
		 WHERE r.run_id IN ( \
		     SELECT MAX(run_id) FROM runs GROUP BY case_id \
		 ) \
		 ORDER BY r.score ASC LIMIT 5"

clean:
	rm -f $(DB) /app/test_cases/output_*.txt
