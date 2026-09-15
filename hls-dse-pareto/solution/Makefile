.PHONY: all evaluate optimize statistics report

all: report

evaluate: output/full_results.csv

output/full_results.csv:
	python3 dse_tool.py --mode evaluate

optimize: output/pareto_fronts.json

output/pareto_fronts.json: output/full_results.csv
	python3 dse_tool.py --mode optimize

statistics: output/pass_at_k.json

output/pass_at_k.json: output/full_results.csv
	python3 dse_tool.py --mode statistics

report: output/dse_summary.json

output/dse_summary.json: output/pareto_fronts.json output/pass_at_k.json
	python3 dse_tool.py --mode report
