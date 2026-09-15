# Quantum chemistry pipeline orchestration
# Targets: audit, run, summary

DATABASE = /app/molecules.db
RESULTS = /app/output/results.json
AUDIT = /app/db_audit.txt
SUMMARY = /app/summary.json

.PHONY: all audit run summary clean

all: run summary

audit:
	@echo "=== Database Audit ===" > $(AUDIT)
	sqlite3 $(DB_PATH) ".schema" >> $(AUDIT)
	@echo "" >> $(AUDIT)
	@echo "=== Row Counts ===" >> $(AUDIT)
	sqlite3 $(DB_PATH) "SELECT 'molecular_systems: ' || COUNT(*) FROM molecular_systems;" >> $(AUDIT)
	sqlite3 $(DB_PATH) "SELECT 'one_body: ' || COUNT(*) FROM one_body;" >> $(AUDIT)
	sqlite3 $(DB_PATH) "SELECT 'two_body: ' || COUNT(*) FROM two_body;" >> $(AUDIT)
	@echo "" >> $(AUDIT)
	@echo "=== Systems ===" >> $(AUDIT)
	sqlite3 $(DB_PATH) "SELECT name || ': ' || n_spatial_orbitals || ' orbitals, ' || n_electrons || ' electrons' FROM molecular_systems;" >> $(AUDIT)

run:
	cd /app && python3 src/run_pipeline.py

summary:
	jq 'to_entries | map({(.key + "_energy"): .value.energy, (.key + "_spectral_match"): .value.spectral}) | add' $(RESULTS) > $(SUMMARY)

clean:
	rm -f $(RESULTS) $(AUDIT) $(SUMMARY)
