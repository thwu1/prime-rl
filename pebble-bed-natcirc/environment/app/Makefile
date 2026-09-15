FC = gfortran
FFLAGS = -O2 -fPIC -shared
LIB = libpackedbed.so

all: $(LIB)

$(LIB): src/packed_bed.f90
	$(FC) $(FFLAGS) -o $@ $<

clean:
	rm -f $(LIB)

.PHONY: all clean
