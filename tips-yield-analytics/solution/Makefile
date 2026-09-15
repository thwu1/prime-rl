DB = treasury.db
BUILD = build

.PHONY: db clean

db: $(DB)

$(BUILD)/nominal.csv: data/nominal_yields.xml xsl/nominal.xsl
	mkdir -p $(BUILD)
	xsltproc xsl/nominal.xsl data/nominal_yields.xml > $@

$(BUILD)/real.csv: data/real_yields.xml xsl/real.xsl
	mkdir -p $(BUILD)
	xsltproc xsl/real.xsl data/real_yields.xml > $@

$(DB): $(BUILD)/nominal.csv $(BUILD)/real.csv schema.sql
	rm -f $(DB)
	sqlite3 $(DB) < schema.sql
	python3 tips_analytics.py load

clean:
	rm -rf $(BUILD) $(DB)
