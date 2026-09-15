CXX = g++
CXXFLAGS = -std=c++20 -Wall -Wextra -I include -O2

all: example

example: example.cpp include/coro/task.hpp include/coro/sync_wait.hpp include/coro/generator.hpp include/coro/when_all.hpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f example
