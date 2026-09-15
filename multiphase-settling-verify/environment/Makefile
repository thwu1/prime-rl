.PHONY: all clean validate

all: validate

results.json: mflow_verify.py config.toml
	python3 mflow_verify.py

convergence.tsv:
	python3 extract_convergence.py

convergence.png: plot_convergence.gp
	gnuplot plot_convergence.gp

report.json:
	@echo '{}' > report.json

validate: report.json convergence.png
	jq -e '.verification and .audit' report.json > /dev/null
	@echo "Pipeline complete"

clean:
	rm -f results.json convergence.tsv convergence.png report.json fit.log
