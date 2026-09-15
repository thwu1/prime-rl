CXX = g++
CXXFLAGS = -std=c++17 -O2 -I/usr/include/eigen3
TARGET = capri_scorer

all: $(TARGET)

$(TARGET): capri_scorer.cpp
	$(CXX) $(CXXFLAGS) -o $(TARGET) capri_scorer.cpp

clean:
	rm -f $(TARGET)

.PHONY: all clean
