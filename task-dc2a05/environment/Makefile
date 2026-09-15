CXX = g++
CXXFLAGS = -std=c++17 -pthread -O2 -Iinclude

.PHONY: all clean

all: build/concurrent_hashmap.o

build/concurrent_hashmap.o: src/concurrent_hashmap.cpp include/concurrent_hashmap.h include/qsbr.h include/hash_util.h
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -rf build
