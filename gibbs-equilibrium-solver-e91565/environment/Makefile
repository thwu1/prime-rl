CXX      = g++
CXXFLAGS = -O2 -std=c++17 -Wall -Wextra
TARGET   = equilibrium

all: $(TARGET)

$(TARGET): equilibrium.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(TARGET) results_*.txt
