PYTHON = python3

.PHONY: all solve convergence plot import_db validate clean

all: validate

solve:
	$(PYTHON) run_solver.py

convergence:
	$(PYTHON) -m convergence.analyze

plot: convergence
	gnuplot /app/plot_convergence.gp

import_db: solve convergence
	bash /app/import_results.sh

validate: solve convergence plot import_db
	@$(PYTHON) validate.py

clean:
	rm -rf /app/results
