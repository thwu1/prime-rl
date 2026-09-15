
CXX = g++
CXXFLAGS = -std=c++20 -O2 -Wall -Wextra -pthread
INCLUDES = -Iinclude

.PHONY: all clean tsan

all: market_feed

market_feed: src/market_feed.cpp include/spsc_queue.hpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< -o $@

tsan: src/market_feed.cpp include/spsc_queue.hpp
	$(CXX) -std=c++20 -O1 -g -fsanitize=thread -pthread $(INCLUDES) $< -o market_feed_tsan
	@echo "Run: ./market_feed_tsan"

clean:
	rm -f market_feed market_feed_tsan
