.PHONY: all parse-tables analyze run-mutated run-standard diverge clean

all: parse-tables analyze run-mutated run-standard diverge

parse-tables:
	cd /app && python3 -c "import imp_parser"

analyze: parse-tables
	cd /app && python3 analyze.py

run-mutated: parse-tables
	cd /app && python3 run_all.py mutated

run-standard: parse-tables
	cd /app && python3 run_all.py standard

diverge: run-mutated run-standard
	cd /app && python3 run_all.py diverge

clean:
	rm -f /app/parsetab.py /app/parser.out
	rm -rf /app/__pycache__
	rm -f /app/results/*.json /app/results_standard/*.json /app/analysis/*.json
