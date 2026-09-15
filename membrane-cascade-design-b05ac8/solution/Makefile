
.PHONY: all preprocess database report clean

all: preprocess database report

preprocess:
	mkdir -p /app/processed
	@for f in /app/data/nist/*.tsv; do \
		base=$$(basename "$$f" .tsv); \
		gas=$${base%%_*}; \
		pressure=$$(echo "$$base" | sed 's/.*_//;s/atm//'); \
		case "$$gas" in \
			N2)  mw=0.028014 ;; \
			O2)  mw=0.031999 ;; \
			CO2) mw=0.044010 ;; \
			CH4) mw=0.016043 ;; \
			H2)  mw=0.002016 ;; \
			He)  mw=0.004003 ;; \
			*)   continue ;; \
		esac; \
		awk -F'\t' -v gas="$$gas" -v patm="$$pressure" -v mw="$$mw" -v R=8.314462 \
			'BEGIN { OFS="," } \
			NR==1 { print "gas,temperature_k,pressure_atm,density_kg_m3,z_nist"; next } \
			{ phase=$$NF; gsub(/[[:space:]]/, "", phase) } \
			phase == "vapor" { \
				T=$$1+0; rho=$$3+0; P_pa=patm*101325.0; \
				z=0; if (rho > 0) z = P_pa * mw / (rho * R * T); \
				printf "%s,%.2f,%s,%.5f,%.8f\n", gas, T, patm, rho, z \
			}' "$$f" > "/app/processed/$$base.csv"; \
	done

database: preprocess
	rm -f /app/analysis.db
	sqlite3 /app/analysis.db " \
		CREATE TABLE nist_reference(gas TEXT, temperature_k REAL, pressure_atm REAL, density_kg_m3 REAL, z_nist REAL); \
		CREATE TABLE eos_validation(gas TEXT, temperature_k REAL, pressure_bar REAL, z_computed REAL, z_nist REAL, relative_error REAL); \
		CREATE TABLE robeson_ranking(gas_pair TEXT, polymer TEXT, p_a REAL, alpha REAL, p_upper_bound REAL, ratio REAL, exceeds_bound INTEGER); \
		CREATE VIEW worst_eos_errors AS SELECT gas, temperature_k, relative_error FROM eos_validation ORDER BY relative_error DESC LIMIT 10; \
	"
	@for f in /app/processed/*.csv; do \
		sqlite3 /app/analysis.db ".mode csv" ".import --skip 1 $$f nist_reference"; \
	done
	@for combo in N2:1 O2:1 CO2:1 CH4:1 H2:1 N2:50 H2:50; do \
		gas=$${combo%%:*}; pressure=$${combo##*:}; \
		python3 -m membrane_analysis validate --gas "$$gas" --pressure "$$pressure" | \
			jq -r ".[] | [\"$$gas\", .T_K, .P_bar, .Z_computed, .Z_nist, .relative_error] | @csv" \
			> /tmp/eos_$${gas}_$${pressure}.csv; \
		sqlite3 /app/analysis.db ".mode csv" ".import /tmp/eos_$${gas}_$${pressure}.csv eos_validation"; \
	done
	@for gp in O2/N2 CO2/CH4 H2/N2 He/N2 CO2/N2 H2/CH4 He/CH4 H2/CO2 He/H2 N2/CH4; do \
		safe=$$(echo "$$gp" | tr '/' '_'); \
		python3 -m membrane_analysis robeson --gas-pair "$$gp" | \
			jq -r ".[] | [\"$$gp\", .polymer, .P_A, .alpha, .P_upper_bound, .ratio, (if .exceeds_bound then 1 else 0 end)] | @csv" \
			> /tmp/robeson_$${safe}.csv; \
		sqlite3 /app/analysis.db ".mode csv" ".import /tmp/robeson_$${safe}.csv robeson_ranking"; \
	done

report: database
	@total=$$(sqlite3 /app/analysis.db "SELECT COUNT(*) FROM nist_reference;"); \
	mean_err=$$(sqlite3 /app/analysis.db "SELECT AVG(relative_error) FROM eos_validation;"); \
	max_err=$$(sqlite3 /app/analysis.db "SELECT MAX(relative_error) FROM eos_validation;"); \
	polymers=$$(sqlite3 /app/analysis.db "SELECT DISTINCT polymer FROM robeson_ranking WHERE exceeds_bound=1;" | jq -R -s 'split("\n") | map(select(length>0))'); \
	n_pairs=$$(sqlite3 /app/analysis.db "SELECT COUNT(DISTINCT gas_pair) FROM robeson_ranking;"); \
	jq -n --argjson total "$$total" --argjson mean "$$mean_err" --argjson max "$$max_err" \
		--argjson polymers "$$polymers" --argjson pairs "$$n_pairs" \
		'{total_nist_points: $$total, mean_relative_error: $$mean, max_relative_error: $$max, polymers_exceeding_bound: $$polymers, gas_pairs_evaluated: $$pairs}' \
		> /app/report.json

clean:
	rm -rf /app/processed /app/analysis.db /app/report.json /tmp/eos_*.csv /tmp/robeson_*.csv
