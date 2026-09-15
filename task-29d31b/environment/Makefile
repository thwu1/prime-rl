.PHONY: all solve analyze report clean

DB = /app/sokoban.db

all: report
	@echo "Pipeline complete."

solve:
	@echo "=== Solving levels ==="
	python3 /app/solver.py
	@sqlite3 $(DB) "SELECT COUNT(*) FROM solutions;" | grep -q '^5$$'
	@echo "Solutions table verified."

analyze: solve
	@echo "=== Analyzing state spaces ==="
	python3 /app/analyzer.py
	@sqlite3 $(DB) "SELECT COUNT(*) FROM state_metrics;" | grep -q '^5$$'
	@sqlite3 $(DB) "SELECT COUNT(*) FROM deadlock_census;" | grep -q '^5$$'
	@echo "Analysis tables verified."

report: analyze
	@echo "=== Generating report ==="
	sqlite3 -json $(DB) "SELECT l.id, l.name, s.num_pushes, s.num_moves, (SELECT COUNT(*) FROM dead_squares d WHERE d.level_id = l.id) AS dead_square_count, m.reachable_states, m.solution_depth, c.corner_deadlocks, c.freeze_deadlocks FROM levels l JOIN solutions s ON s.level_id = l.id JOIN state_metrics m ON m.level_id = l.id JOIN deadlock_census c ON c.level_id = l.id ORDER BY m.reachable_states DESC;" | jq '{levels: ., difficulty_ranking: [.[].id]}' > /app/report.json
	@echo "Report written to /app/report.json"

clean:
	sqlite3 $(DB) "DROP TABLE IF EXISTS solutions; DROP TABLE IF EXISTS dead_squares; DROP TABLE IF EXISTS state_metrics; DROP TABLE IF EXISTS deadlock_census;"
	rm -f /app/report.json
