# Makefile for metadynamics FES analysis pipeline

.PHONY: fes converge clean

fes:
	python3 /app/sum_hills --hills $(HILLS) --grid-min=$(GRID_MIN) --grid-max=$(GRID_MAX) --grid-bins=$(GRID_BINS) --periodic=$(PERIODIC) --outfile $(OUTFILE)

converge:
	python3 /app/converge.py --hills $(HILLS) --grid-min=$(GRID_MIN) --grid-max=$(GRID_MAX) --grid-bins=$(GRID_BINS) --periodic=$(PERIODIC) --windows $(WINDOWS) --outfile $(OUTFILE)

clean:
	rm -f /app/_conv_window_*.dat /app/_conv_fes_*.dat
	rm -f /app/fes_*.dat /app/convergence_*.json /app/_test_*.dat /app/_test_*.json
