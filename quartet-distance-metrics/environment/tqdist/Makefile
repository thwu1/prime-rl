CXX = g++
CXXFLAGS = -O2 -std=c++17
TARGET = tqdist

all: $(TARGET)

$(TARGET): tqdist.cpp
	$(CXX) $(CXXFLAGS) -o $(TARGET) tqdist.cpp

clean:
	rm -f $(TARGET)
