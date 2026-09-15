.DELETE_ON_ERROR:

PROGRAMS := $(basename $(notdir $(wildcard programs/*.tac)))
OPT_FILES := $(patsubst %,output/%.tac,$(PROGRAMS))

.PHONY: all validate report clean

all: $(OPT_FILES) validate report

output/%.tac: programs/%.tac optimizer.py
	@mkdir -p output
	python3 optimizer.py $< > $@

validate: $(OPT_FILES)
	@for f in $(OPT_FILES); do \
		python3 tac_check.py "$$f" || exit 1; \
	done

report: $(OPT_FILES)
	@mkdir -p output
	python3 gen_report.py > output/report.json

clean:
	rm -rf output
