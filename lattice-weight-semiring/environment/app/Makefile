CXX = g++
CXXFLAGS = -std=c++17 -O2 -g -Wall -Wextra -Wno-unused-parameter
TARGET = test_main

all: $(TARGET)

$(TARGET): test_main.cpp lattice_weight.h
	$(CXX) $(CXXFLAGS) -o $(TARGET) test_main.cpp

clean:
	rm -f $(TARGET)

.PHONY: all clean
