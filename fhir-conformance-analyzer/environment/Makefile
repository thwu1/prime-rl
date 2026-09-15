# FHIR US Core Conformance Checker Pipeline
# Orchestrates jq filters and Python scripts to produce a conformance report.
#
# Usage: make          (builds /app/output/conformance_report.json)
#        make clean    (removes intermediate and output files)

BUILD   = /app/build
OUTPUT  = /app/output
DATA    = /app/data
FILTERS = /app/filters
CHECKER = /app/checker

BUNDLES = $(sort $(wildcard $(DATA)/bundles/*.json))

.PHONY: all clean

all: $(OUTPUT)/conformance_report.json

# Step 1: Extract all FHIR resources from Bundle files
$(BUILD)/resources.json: $(BUNDLES)
	@mkdir -p $(BUILD)
	jq -s '[.[].entry[].resource]' $(BUNDLES) > $@

# Step 2: Must Support element coverage analysis (Python)
$(BUILD)/must_support.json: $(BUILD)/resources.json $(DATA)/us_core_manifest.json $(CHECKER)/must_support.py
	python3 $(CHECKER)/must_support.py > $@

# Step 3: CapabilityStatement gap analysis (jq)
$(BUILD)/capability_gaps.json: $(DATA)/capability_statement.json $(DATA)/us_core_manifest.json $(FILTERS)/capability.jq
	jq --slurpfile manifest $(DATA)/us_core_manifest.json -f $(FILTERS)/capability.jq $(DATA)/capability_statement.json > $@

# Step 4: Reference integrity analysis (Python)
$(BUILD)/reference_integrity.json: $(BUILD)/resources.json $(CHECKER)/references.py
	python3 $(CHECKER)/references.py > $@

# Step 5: Assemble final report with scoring (jq)
$(OUTPUT)/conformance_report.json: $(BUILD)/must_support.json $(BUILD)/capability_gaps.json $(BUILD)/reference_integrity.json $(FILTERS)/assemble.jq
	@mkdir -p $(OUTPUT)
	jq -n --slurpfile ms $(BUILD)/must_support.json --slurpfile cg $(BUILD)/capability_gaps.json --slurpfile ri $(BUILD)/reference_integrity.json -f $(FILTERS)/assemble.jq > $@

clean:
	rm -rf $(BUILD) $(OUTPUT)
