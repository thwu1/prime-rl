.PHONY: all run plot clean

all: run plot

run:
	python3 /app/mhd_solver.py

plot:
	gnuplot /app/plot_density.gp

clean:
	rm -f /app/results.json /app/density_final.dat /app/density_contour.png
