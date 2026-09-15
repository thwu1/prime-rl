CXX = g++
CXXFLAGS = -Wall -Wextra -O2 -g -std=gnu++17
SRCS = server.cpp hashtable.cpp avl.cpp zset.cpp heap.cpp thread_pool.cpp
OBJS = $(SRCS:.cpp=.o)
TARGET = server

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^ -lpthread

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
