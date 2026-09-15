SHELL = /bin/sh
.SUFFIXES: .cc .o

LULESH_EXEC = lulesh2.0

CXX = g++ -DUSE_MPI=0
CXXFLAGS = -g -O3 -I. -Wall
LDFLAGS = -g -O3

SOURCES = \
	lulesh.cc \
	lulesh-comm.cc \
	lulesh-viz.cc \
	lulesh-util.cc \
	lulesh-init.cc
OBJECTS = $(SOURCES:.cc=.o)

.cc.o: lulesh.h
	@echo "Building $<"
	$(CXX) -c $(CXXFLAGS) -o $@ $<

all: $(LULESH_EXEC)

$(LULESH_EXEC): $(OBJECTS)
	@echo "Linking"
	$(CXX) $(OBJECTS) $(LDFLAGS) -lm -o $@

clean:
	/bin/rm -f *.o *~ $(LULESH_EXEC)
	/bin/rm -rf *.dSYM
