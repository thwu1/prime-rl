CXX = g++
CXXFLAGS = -std=c++20 -O2 -pthread -I.

all: trading_sim

trading_sim: trading_sim.cpp spsc_queue.hpp feed_merger.hpp market_data.hpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f trading_sim

.PHONY: all clean
