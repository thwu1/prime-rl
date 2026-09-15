.PHONY: all clean

all: libgaml.so

libgaml.so: fortran/gaml_core.f90
	gfortran -shared -fPIC -O2 -o $@ $<

clean:
	rm -f libgaml.so
