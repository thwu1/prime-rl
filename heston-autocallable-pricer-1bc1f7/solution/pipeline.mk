
SHELL := /bin/bash
DB := /app/pricing.db
PRICER := python3 /app/pricer.py
CSV := /app/data/heston_reference.csv
CORR_IN := /app/data/correlation_sample.json
CORR_OUT := /app/data/correlation_cleaned.json
NOTE_CFG := /app/data/note_config.json
REPORT := /app/report.txt

.PHONY: all db-init calibrate clean price-note report

all: report

db-init:
	@rm -f $(DB)
	@sqlite3 $(DB) "CREATE TABLE heston_results (strike REAL, reference_price REAL, computed_price REAL, abs_error REAL); CREATE TABLE autocall_results (config_name TEXT, price REAL, std_error REAL, autocall_prob_json TEXT, expected_coupon_count REAL);"

calibrate: db-init
	@tail -n +2 $(CSV) | while IFS=, read -r spot strike rate maturity v0 theta kappa sigma rho div_yield ref_price; do \
		computed=$$($(PRICER) heston-call \
			--spot "$$spot" --strike "$$strike" --rate "$$rate" \
			--maturity "$$maturity" --v0 "$$v0" --theta "$$theta" \
			--kappa "$$kappa" --sigma "$$sigma" --rho "$$rho" \
			--div-yield "$$div_yield" | jq -r '.price'); \
		abs_err=$$(python3 -c "print(abs($$computed - $$ref_price))"); \
		sqlite3 $(DB) "INSERT INTO heston_results VALUES($$strike, $$ref_price, $$computed, $$abs_err)"; \
	done

clean: db-init
	@$(PRICER) clean-corr --input-file $(CORR_IN) --output-file $(CORR_OUT)

price-note: calibrate clean
	@result=$$($(PRICER) autocallable --config $(NOTE_CFG)); \
	price=$$(echo "$$result" | jq -r '.price'); \
	std_err=$$(echo "$$result" | jq -r '.std_error'); \
	autocall_probs=$$(echo "$$result" | jq -c '.autocall_prob'); \
	exp_coupons=$$(echo "$$result" | jq -r '.expected_coupon_count'); \
	sqlite3 $(DB) "INSERT INTO autocall_results VALUES('default', $$price, $$std_err, '$$autocall_probs', $$exp_coupons)"

report: price-note
	@echo "=== Heston Calibration ===" > $(REPORT)
	@sqlite3 $(DB) "SELECT 'max_error: ' || printf('%.6f', MAX(abs_error)) FROM heston_results;" >> $(REPORT)
	@sqlite3 $(DB) "SELECT 'mean_error: ' || printf('%.6f', AVG(abs_error)) FROM heston_results;" >> $(REPORT)
	@sqlite3 $(DB) "SELECT 'num_strikes: ' || COUNT(*) FROM heston_results;" >> $(REPORT)
	@echo "=== Autocallable Pricing ===" >> $(REPORT)
	@sqlite3 $(DB) "SELECT 'config: ' || config_name || ', price: ' || printf('%.6f', price) || ', std_error: ' || printf('%.6f', std_error) || ', expected_coupons: ' || printf('%.4f', expected_coupon_count) FROM autocall_results;" >> $(REPORT)
