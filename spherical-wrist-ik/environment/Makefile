CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -I include
SOURCES = src/fk.cpp src/ik.cpp src/main.cpp
TARGET = manipulator

$(TARGET): $(SOURCES) include/manipulator.h
	$(CXX) $(CXXFLAGS) $(SOURCES) -o $(TARGET) -lm

clean:
	rm -f $(TARGET)

.PHONY: clean
