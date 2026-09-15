CXX = g++
CXXFLAGS = -O2 -std=c++17 -ffp-contract=off -Wall
TARGET = test_predicates

SRCS = main.cpp predicates.cpp
HDRS = predicates.hpp expansion.hpp

$(TARGET): $(SRCS) $(HDRS)
	$(CXX) $(CXXFLAGS) -o $(TARGET) $(SRCS)

clean:
	rm -f $(TARGET)

.PHONY: clean
