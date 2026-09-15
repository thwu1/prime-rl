CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
LDFLAGS = -lpthread

all: stream_analyzer

stream_analyzer: stream_analyzer.cpp simdjson.cpp simdjson.h
	$(CXX) $(CXXFLAGS) -o $@ stream_analyzer.cpp simdjson.cpp $(LDFLAGS)

clean:
	rm -f stream_analyzer

.PHONY: all clean
