# Geotechnical Settlement Analysis Pipeline

PYTHON = python
GEOSETTLE = geosettle.py
PREPROCESSOR = tools/preprocess.py
STORER = tools/store_results.py
SCHEMA = tools/schema.sql

.PHONY: all clean

all: results.db

# Preprocessing: CSV + INI -> JSON scenario
sites/site_a/scenario.json: sites/site_a/config.ini sites/site_a/soil_profile.csv $(PREPROCESSOR)
	$(PYTHON) $(PREPROCESSOR) --config sites/site_a/config.ini --soil sites/site_a/soil_profile.csv --output $@

sites/site_b/scenario.json: sites/site_b/config.ini sites/site_b/soil_profile.csv $(PREPROCESSOR)
	$(PYTHON) $(PREPROCESSOR) --config sites/site_b/config.ini --soil sites/site_b/soil_profile.csv --output $@

sites/site_c/scenario.json: sites/site_c/config.ini $(PREPROCESSOR)
	$(PYTHON) $(PREPROCESSOR) --config sites/site_c/config.ini --output $@

# Analysis: run settlement/consolidation engine
sites/site_a/results.json: $(GEOSETTLE)
	$(PYTHON) $(GEOSETTLE) sites/site_a/scenario.json > $@

sites/site_b/results.json: $(GEOSETTLE)
	$(PYTHON) $(GEOSETTLE) sites/site_b/scenario.json > $@

sites/site_c/results.json: $(GEOSETTLE)
	$(PYTHON) $(GEOSETTLE) sites/site_c/scenario.json > $@

# Store results in SQLite database
results.db: sites/site_a/results.json sites/site_b/results.json sites/site_c/results.json $(SCHEMA)
	rm -f $@
	sqlite3 $@ < $(SCHEMA)
	$(PYTHON) $(STORER) $@ site_a site_b site_c

clean:
	rm -f results.db
	rm -f sites/*/scenario.json sites/*/results.json
