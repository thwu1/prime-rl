CXX = g++
CXXFLAGS = -O2 -std=c++17
LDFLAGS = -lm

pipeline: pipeline.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f pipeline

.PHONY: clean
