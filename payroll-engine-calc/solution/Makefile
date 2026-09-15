
.PHONY: all run validate report

all:
	$(MAKE) run
	$(MAKE) validate
	$(MAKE) report

run:
	python3 payroll_engine.py

validate:
	jq -ef payroll_validator.jq payroll_output.json > /dev/null

report:
	printf 'scenario_id,type,gross,net\n' > payroll_report.csv
	jq -r '.results | sort_by(.id) | .[] | "\(.id) \(.type) \(if .type == "regular" or .type == "regular_with_garnishment" then .gross_pay elif .type == "bonus_aggregate" then .bonus_gross elif .type == "gross_up" then .computed_gross else .total_retro_gross end) \(if .type == "regular" then .net_pay elif .type == "regular_with_garnishment" then .net_pay_after_garnishment elif .type == "bonus_aggregate" then .net_bonus elif .type == "gross_up" then .actual_net else .net_retro end)"' payroll_output.json | awk '{printf "%s,%s,%.2f,%.2f\n", $$1, $$2, $$3, $$4}' >> payroll_report.csv
