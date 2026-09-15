CXX = g++
CXXFLAGS = -std=c++20 -pthread -Wall

all: test_concurrent

test_concurrent: test_concurrent.cpp lockfree_stack.hpp $(wildcard memory_reclamation.hpp)
	$(CXX) $(CXXFLAGS) -O1 -o $@ $<

test_asan: test_concurrent.cpp lockfree_stack.hpp $(wildcard memory_reclamation.hpp)
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address -fno-omit-frame-pointer -o $@ $<

clean:
	rm -f test_concurrent test_asan

.PHONY: all clean
