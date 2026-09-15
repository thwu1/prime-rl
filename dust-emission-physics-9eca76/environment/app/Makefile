FC = gfortran
FFLAGS = -O2

all: dust_emission

dust_emission: dust_physics_mod.f90 dust_k14_mod.f90 main.f90
	$(FC) $(FFLAGS) -c dust_physics_mod.f90
	$(FC) $(FFLAGS) -c dust_k14_mod.f90
	$(FC) $(FFLAGS) -c main.f90
	$(FC) $(FFLAGS) -o dust_emission dust_physics_mod.o dust_k14_mod.o main.o

clean:
	rm -f *.o *.mod dust_emission

.PHONY: all clean
