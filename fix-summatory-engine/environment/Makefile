CXX = g++
CXXFLAGS = -O2 -std=c++17 -Wall -Wextra
TARGET = engine

all: $(TARGET)

$(TARGET): engine.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
