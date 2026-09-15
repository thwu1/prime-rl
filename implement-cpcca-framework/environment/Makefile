PYTHON := python3
DATA := data/fields.h5
OUTDIR := results

.PHONY: all clean

all: $(OUTDIR)/validation.log

$(OUTDIR)/decomposition.npz: $(DATA)
	mkdir -p $(OUTDIR)
	$(PYTHON) pipeline.py --n-modes 5 --output $(OUTDIR)/output.npz

$(OUTDIR)/validation.log: $(OUTDIR)/decomposition.npz
	$(PYTHON) validate_results.py $< > $@

clean:
	rm -rf $(OUTDIR)
