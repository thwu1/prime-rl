.PHONY: setup test info clean

PYTHON ?= python3
MODEL_VARIANT ?= glm5-9b

setup:
	@command -v jq >/dev/null 2>&1 || { echo "Error: jq is required but not installed"; exit 1; }
	@echo "Extracting configuration for variant: $(MODEL_VARIANT)"
	jq '.variants["$(MODEL_VARIANT)"]' configs/glm5_registry.json > configs/active_config.json
	@echo "Active configuration written to configs/active_config.json"

test: setup
	cd /app && $(PYTHON) -m pytest /tests/test_state.py -v

info:
	@echo "=== Model Registry ==="
	@echo "Available variants:"
	@jq -r '.variants | keys[]' configs/glm5_registry.json 2>/dev/null || echo "  (registry not found)"
	@echo ""
	@echo "Default variant: $(MODEL_VARIANT)"
	@echo ""
	@echo "=== Active Configuration ==="
	@if [ -f configs/active_config.json ]; then \
		jq '.' configs/active_config.json; \
	else \
		echo "  (not yet initialized — run 'make setup')"; \
	fi

clean:
	rm -f configs/active_config.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
