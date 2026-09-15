CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra

rotation_math.o: rotation_math.cpp rotation_math.hpp
	$(CXX) $(CXXFLAGS) -c rotation_math.cpp -o rotation_math.o

clean:
	rm -f *.o test_runner

.PHONY: clean
