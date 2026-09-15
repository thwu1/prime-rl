CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra

all: run_tests

charconv.o: charconv.cpp charconv.hpp
	$(CXX) $(CXXFLAGS) -c charconv.cpp -o charconv.o

run_tests: smoketest.cpp charconv.o
	$(CXX) $(CXXFLAGS) -o run_tests smoketest.cpp charconv.o

clean:
	rm -f *.o run_tests

.PHONY: all clean
