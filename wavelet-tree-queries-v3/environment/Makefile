CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra
TARGET = wt

SRCS = $(wildcard src/*.cpp)
HDRS = $(wildcard src/*.hpp src/*.h)

$(TARGET): $(SRCS) $(HDRS)
	$(CXX) $(CXXFLAGS) -Isrc -o $(TARGET) $(SRCS)

debug: $(SRCS) $(HDRS)
	$(CXX) -std=c++17 -g -O0 -fsanitize=address,undefined -fno-omit-frame-pointer -Isrc -o $(TARGET) $(SRCS)

clean:
	rm -f $(TARGET)

.PHONY: clean debug
