CXX = g++
CXXFLAGS = -Wall -Wextra -O2 -g -std=c++17
LDFLAGS = -lpthread

all: server client

server: server.cpp hashtable.cpp avl.cpp zset.cpp heap.cpp thread_pool.cpp \
        common.h hashtable.h avl.h zset.h heap.h list.h thread_pool.h
	$(CXX) $(CXXFLAGS) -o $@ server.cpp hashtable.cpp avl.cpp zset.cpp heap.cpp thread_pool.cpp $(LDFLAGS)

client: client.cpp
	$(CXX) $(CXXFLAGS) -o $@ client.cpp

clean:
	rm -f server client

.PHONY: all clean
