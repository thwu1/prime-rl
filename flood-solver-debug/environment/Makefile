CXX = g++
CXXFLAGS = -O2 -Wall -std=c++17
TARGET = flood_solver

SRCS = src/main.cpp src/solver.cpp
HDRS = src/solver.h

$(TARGET): $(SRCS) $(HDRS)
	$(CXX) $(CXXFLAGS) -I src -o $(TARGET) $(SRCS) -lm

clean:
	rm -f $(TARGET) results_*.asc results_*.csv results_*.txt

.PHONY: clean
