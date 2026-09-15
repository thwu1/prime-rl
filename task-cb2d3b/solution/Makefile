.PHONY: all run plots clean

all: run plots

run:
	python3 mhd_solver.py

plots:
	gnuplot output/density.gp
	gnuplot output/divB.gp

clean:
	rm -rf output/*
