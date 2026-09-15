CXX = g++
CXXFLAGS = -Wall -Wextra -O2 -g -std=c++17

server: server.cpp avl.cpp hashtable.cpp zset.cpp
	$(CXX) $(CXXFLAGS) -o server server.cpp avl.cpp hashtable.cpp zset.cpp

clean:
	rm -f server

.PHONY: clean
