.PHONY: all run report validate clean

all: run report validate

run:
	cd /app && python3 run_study.py

report:
	# Generate convergence analysis report from simulation output.
	# Transform /app/results/convergence.json into /app/results/report.json
	# using jq. The input JSON has structure:
	#   {"polynomial_degree": N, "elements": [...], "errors": [...], "orders": [...]}
	# The output JSON must contain exactly these keys:
	#   mean_order  (float) - arithmetic mean of all values in "orders"
	#   max_error   (float) - maximum value from "errors"
	#   min_error   (float) - minimum value from "errors"
	#   num_levels  (int)   - number of entries in "elements"
	@echo "STUB: replace this entire line with a jq pipeline" && exit 1

validate:
	# Validate physical correctness of the Sod shock tube solution.
	# Read /app/results/sod_solution.csv (header row: x,rho,v,p).
	# Check that every density value (field 2) and every pressure
	# value (field 4) in all data rows is strictly positive.
	# Write exactly "PASS" to /app/results/validation.txt if all
	# checks pass, or "FAIL" otherwise. Use awk to process the CSV.
	@echo "STUB: replace this entire line with an awk pipeline" && exit 1

clean:
	rm -rf /app/results
