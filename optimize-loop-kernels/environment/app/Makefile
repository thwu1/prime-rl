CXX = g++
CXXFLAGS = -O3 -std=c++17 -Wall
LDFLAGS = -lm

SRCS = main.cpp kernels.cpp transform.cpp
OBJS = $(SRCS:.cpp=.o)
TARGET = benchmark

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
