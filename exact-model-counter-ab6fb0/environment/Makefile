CXX = g++
CXXFLAGS = -O2 -Wall -std=c++17
LDFLAGS = -lgmpxx -lgmp

mc: mc.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

.PHONY: clean
clean:
	rm -f mc
