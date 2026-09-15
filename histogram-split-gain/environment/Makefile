CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall
TARGET = histogram_split_finder

all: $(TARGET)

$(TARGET): main.cpp split_math.hpp histogram_scanner.hpp
	$(CXX) $(CXXFLAGS) -o $(TARGET) main.cpp

clean:
	rm -f $(TARGET)
