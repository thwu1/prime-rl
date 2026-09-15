"""
Deploy the Makefile and jq filter for the benchmark pipeline.
Creates /app/Makefile with benchmark, report, and all targets.
"""

MAKEFILE_CONTENT = """.PHONY: all benchmark report

all: benchmark report

benchmark:
\trm -f /app/results.db
\tpython3 /opt/optframework/run_test.py --csv > /tmp/_bench_output.csv
\tsqlite3 /app/results.db "CREATE TABLE benchmark (problem TEXT NOT NULL, seeds_total INTEGER NOT NULL, seeds_feasible INTEGER NOT NULL, mean_objective REAL NOT NULL, budget_violations INTEGER NOT NULL);"
\tprintf '.mode csv\\n.import /tmp/_bench_output.csv benchmark\\n' | sqlite3 /app/results.db

report:
\tsqlite3 -json /app/results.db "SELECT * FROM benchmark ORDER BY problem;" | jq '{problems: [.[] | {name: .problem, feasibility_rate: (.seeds_feasible / .seeds_total), mean_objective: .mean_objective, budget_violations: .budget_violations, pass: ((.seeds_feasible / .seeds_total >= 0.95) and (.budget_violations == 0) and (((.problem == "prob1") and (.mean_objective <= 0.5)) or ((.problem == "prob2") and (.mean_objective <= 10.0)) or ((.problem == "prob3") and (.mean_objective <= 1.0)) or ((.problem == "prob4") and (.mean_objective <= 5.0)) or ((.problem == "prob5") and (.mean_objective <= 25.0))))}], overall_pass: ([.[] | ((.seeds_feasible / .seeds_total >= 0.95) and (.budget_violations == 0) and (((.problem == "prob1") and (.mean_objective <= 0.5)) or ((.problem == "prob2") and (.mean_objective <= 10.0)) or ((.problem == "prob3") and (.mean_objective <= 1.0)) or ((.problem == "prob4") and (.mean_objective <= 5.0)) or ((.problem == "prob5") and (.mean_objective <= 25.0))))] | all)}' > /app/report.json
"""

with open('/app/Makefile', 'w') as fp:
    fp.write(MAKEFILE_CONTENT)

print("Makefile deployed to /app/Makefile")
