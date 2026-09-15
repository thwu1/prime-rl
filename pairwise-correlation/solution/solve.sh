#!/bin/bash

# Copy the complete solution into the app directory
cp /solution/main_solution.cpp /app/main.cpp

# Write the correct Makefile to ensure test fixture compilation works
cat > /app/Makefile << 'MAKEEOF'
CXX = g++
CXXFLAGS = -O2 -std=c++17 -Wall -Wextra

correlation: main.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< -lm

clean:
	rm -f correlation

.PHONY: clean
MAKEEOF

# Compile directly
cd /app
g++ -O2 -std=c++17 -Wall -Wextra -o correlation main.cpp -lm
