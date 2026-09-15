PYTHON = python3

.PHONY: all solve convergence plot import_db validate clean

all: validate

solve:
	$(PYTHON) /app/src/run_solver.py

convergence:
	$(PYTHON) -m convergence

plot: solve
	gnuplot /app/plot_convergence.gp

import_db: solve
	bash /app/import_results.sh

validate: solve
	@$(PYTHON) validate.py

clean:
	rm -rf /app/results
