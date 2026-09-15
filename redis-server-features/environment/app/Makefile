CXX = g++
CXXFLAGS = -Wall -Wextra -O2 -std=c++17 -g
LDFLAGS = -lpthread

SERVER_SRCS = server.cpp avl.cpp hashtable.cpp zset.cpp heap.cpp thread_pool.cpp
SERVER_OBJS = $(SERVER_SRCS:.cpp=.o)

all: server

server: $(SERVER_OBJS)
	$(CXX) -o $@ $^ $(LDFLAGS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f *.o server

.PHONY: all clean
