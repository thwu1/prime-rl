FC = gfortran
FFLAGS = -O2 -fPIC

all: libthermal.so

libthermal.so: thermal.f90
	$(FC) $(FFLAGS) -shared thermal.f90 -o libthermal.so

clean:
	rm -f *.o *.so *.mod
