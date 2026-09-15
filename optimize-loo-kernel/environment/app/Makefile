CXX = g++
CXXFLAGS = -O2 -std=c++17 -Wall
TARGET = analytics

all: $(TARGET)

$(TARGET): main.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
