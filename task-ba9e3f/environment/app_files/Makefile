CXX = g++
CXXFLAGS = -O3 -march=native -std=c++17

all: benchmark

benchmark: benchmark.cpp correlate.cpp correlate.h
	$(CXX) $(CXXFLAGS) -o benchmark benchmark.cpp correlate.cpp

clean:
	rm -f benchmark

.PHONY: all clean
