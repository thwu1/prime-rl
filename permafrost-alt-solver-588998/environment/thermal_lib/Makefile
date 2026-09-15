FC = gfortran
FFLAGS = -O2

all: libthermal.a

libthermal.a: thermal.f90
	$(FC) $(FFLAGS) -c thermal.f90 -o thermal.o
	ar rcs libthermal.a thermal.o

clean:
	rm -f *.o *.a *.mod
