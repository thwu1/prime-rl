.PHONY: validate diagram trace-report all clean

all: validate diagram trace-report

validate:
	python3 run_sim.py

diagram:
	python3 gen_diagram.py > protocol.dot
	dot -Tpng protocol.dot -o protocol.svg
	@echo "Diagram generated: protocol.svg"

trace-report:
	python3 run_sim.py --trace trace_workload.json --json-output trace_raw.json
	jq '{ total_operations: (.results | length), upgrade_transactions: [.statistics | to_entries[] | .value.upgrade] | add, getm_transactions: [.statistics | to_entries[] | .value.getm] | add, bank_utilization: [.statistics | to_entries[] | {(.key): ((.value.gets + .value.getm + .value.upgrade))}] | add }' trace_raw.json > trace_report.json
	@echo "Trace report generated: trace_report.json"

clean:
	rm -f protocol.dot protocol.svg trace_raw.json trace_report.json
