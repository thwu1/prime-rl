FC = gfortran
FFLAGS = -O2 -Wall
TARGET = dust_driver

all: $(TARGET)

$(TARGET): dust_physics.o driver.o
	$(FC) $(FFLAGS) -o $@ $^

dust_physics.o: dust_physics.f90
	$(FC) $(FFLAGS) -c $<

driver.o: driver.f90 dust_physics.o
	$(FC) $(FFLAGS) -c $<

clean:
	rm -f *.o *.mod $(TARGET)

.PHONY: all clean
