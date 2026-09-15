
.PHONY: all clean

DATA_DEPS := /app/data/guls.csv /app/data/fm_programme.csv /app/data/fm_profile.csv /app/data/fm_policytc.csv

all: /app/output.csv /app/report.json

/app/.stamp_loaded: $(DATA_DEPS) /app/fmcalc.py
	python3 /app/fmcalc.py load
	@touch $@

/app/.stamp_computed: /app/.stamp_loaded
	python3 /app/fmcalc.py compute
	@touch $@

/app/output.csv: /app/.stamp_computed
	python3 /app/fmcalc.py export

/app/report.json: /app/.stamp_computed
	python3 /app/fmcalc.py report

clean:
	rm -f /app/fm_results.db /app/output.csv /app/report.json /app/.stamp_loaded /app/.stamp_computed
