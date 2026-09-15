PYTHON = python3
DB = coolant.db
SPECS = reactor_specs.json

.PHONY: all verify clean db-schema db-query

all: results.json

results.json: analysis.py $(DB) $(SPECS)
	$(PYTHON) analysis.py

verify: results.json
	@echo "=== Database Schema ==="
	@sqlite3 $(DB) ".schema"
	@echo ""
	@echo "=== Property Data Range ==="
	@sqlite3 -header -column $(DB) \
		"SELECT MIN(temperature_C) AS T_min_C, MAX(temperature_C) AS T_max_C, COUNT(*) AS num_points FROM liquid_properties;"
	@echo ""
	@echo "=== Analysis Results ==="
	@jq '.' results.json
	@echo ""
	@echo "=== Safety Summary ==="
	@jq '{DNBR: .minimum_DNBR, peak_clad_C: .peak_cladding_temperature_C, total_dP_kPa: .total_pressure_drop_kPa}' results.json

db-schema:
	@sqlite3 $(DB) ".tables"
	@sqlite3 $(DB) ".schema liquid_properties"

db-query:
	@sqlite3 -header -column $(DB) "SELECT * FROM liquid_properties ORDER BY temperature_C;"

clean:
	rm -f results.json
