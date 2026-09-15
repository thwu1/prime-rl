.PHONY: bench info clean

PYTHON = python3

info:
	@echo "Available databases:"
	@ls -la /app/*.db 2>/dev/null || echo "  (none)"
	@echo ""
	@echo "baseline.db tables:"
	@sqlite3 /app/baseline.db ".tables" 2>/dev/null || echo "  (not found)"

bench:
	$(PYTHON) evaluate.py

clean:
	rm -f /app/analysis.db /app/optimal_params.json
