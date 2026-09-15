.PHONY: benchmark clean build report

CIRCUITS_DIR := /app/circuits
RESULTS_DIR := /app/results
LIB := /app/quantum_sim/libqsim.so
KERNEL_SRC := /app/quantum_sim/kernel.c
DB := $(RESULTS_DIR)/benchmark.db

build: $(LIB)

$(LIB): $(KERNEL_SRC)
	gcc -shared -fPIC -O2 -o $@ $< -lm

benchmark: build | $(RESULTS_DIR)
	@rm -f $(DB)
	@sqlite3 $(DB) "CREATE TABLE results (name TEXT PRIMARY KEY, n_qubits INTEGER, expectation_value REAL, n_params INTEGER, n_gradients INTEGER);"
	@for f in $(CIRCUITS_DIR)/*.json; do \
		name=$$(jq -r '.name' "$$f") || exit 1; \
		python3 /app/run_circuit.py --gradients "$$f" > $(RESULTS_DIR)/$${name}.json || exit 1; \
		nq=$$(jq -r '.n_qubits' "$$f") || exit 1; \
		ev=$$(jq '.expectation_value' $(RESULTS_DIR)/$${name}.json) || exit 1; \
		npar=$$(jq '.params | length' "$$f") || exit 1; \
		ng=$$(jq '.gradients | length' $(RESULTS_DIR)/$${name}.json) || exit 1; \
		sqlite3 $(DB) "INSERT INTO results VALUES ('$${name}', $${nq}, $${ev}, $${npar}, $${ng});" || exit 1; \
		echo "OK: $${name}"; \
	done

report:
	@sqlite3 -header -column $(DB) "SELECT name, n_qubits, printf('%.6f', expectation_value) AS expectation, n_params, n_gradients FROM results ORDER BY n_qubits;"
	@echo ""
	@sqlite3 $(DB) "SELECT 'Total: ' || COUNT(*) || ' circuits, avg expectation: ' || printf('%.6f', AVG(expectation_value)) FROM results;"

$(RESULTS_DIR):
	mkdir -p $@

clean:
	rm -rf $(RESULTS_DIR) $(LIB)
