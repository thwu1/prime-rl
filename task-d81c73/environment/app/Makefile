CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -pthread

all: pipeline

pipeline: main.cpp spsc_queue.h latency_sampler.h
	$(CXX) $(CXXFLAGS) -o $@ main.cpp

clean:
	rm -f pipeline

.PHONY: all clean
