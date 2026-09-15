.PHONY: pipeline analysis all clean

PYTHON_SRCS = /app/extrapolators.py /app/allocator.py /app/benchmark.py /app/noise_model.py

all: pipeline analysis
	@echo "All tasks complete."

pipeline: /app/report.json
	@echo "Pipeline complete. Report at /app/report.json"

analysis: /app/results.json
	@echo "Analysis complete. Results at /app/results.json"

/app/report.json: /app/raw_results.json /app/postprocess.jq
	jq -f /app/postprocess.jq /app/raw_results.json > /app/report.json

/app/raw_results.json: /app/scenarios.json $(PYTHON_SRCS)
	cd /app && python3 benchmark.py

/app/scenarios.json: /app/calibration.db /app/extract_scenarios.sql
	sqlite3 /app/calibration.db < /app/extract_scenarios.sql > /app/scenarios.json

/app/results.json: /app/zne_optimizer.py /app/run_analysis.py /app/problems.json /app/noise_model.py
	cd /app && python3 run_analysis.py

clean:
	rm -f /app/scenarios.json /app/raw_results.json /app/report.json /app/results.json
