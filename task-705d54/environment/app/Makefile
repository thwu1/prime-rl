.PHONY: check clean

DB = hierarchy.db
VIEWS_STAMP = .views_applied
SQL_VIOLATIONS = sql_violations.json
PY_VIOLATIONS = py_violations.json
OUTPUT = violations.json

check: $(OUTPUT)

$(VIEWS_STAMP): views.sql $(DB)
	sqlite3 $(DB) < views.sql
	touch $@

$(SQL_VIOLATIONS): $(VIEWS_STAMP)
	sqlite3 -json $(DB) "SELECT type, rule FROM v_structural_violations" > $@

$(PY_VIOLATIONS): checker.py $(VIEWS_STAMP)
	python3 checker.py

$(OUTPUT): postprocess.sh $(SQL_VIOLATIONS) $(PY_VIOLATIONS)
	bash postprocess.sh

clean:
	rm -f $(OUTPUT) $(SQL_VIOLATIONS) $(PY_VIOLATIONS) $(VIEWS_STAMP)
