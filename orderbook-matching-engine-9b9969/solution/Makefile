.PHONY: process replay validate serve audit-summary filter-events

process:
	python3 /app/engine.py $(INPUT) $(OUTPUT)

replay:
	python3 /app/engine.py --binary $(INPUT) $(OUTPUT)

validate:
	@failed=0; \
	for scenario in /app/scenarios/*.json; do \
		python3 /app/engine.py --validate "$$scenario" || failed=1; \
	done; \
	exit $$failed

serve:
	python3 /app/engine.py --serve $(HOST):$(PORT)

audit-summary:
	@sqlite3 $(AUDIT_DB) ".mode tabs" "SELECT 'total', COUNT(*) FROM events;" "SELECT type, COUNT(*) FROM events GROUP BY type ORDER BY type;" "SELECT trader, position, balance, total_fees FROM accounts ORDER BY trader;"

filter-events:
	@jq --arg t "$(EVENT_TYPE)" '[.events[] | select(.type == $$t)]' $(INPUT)
