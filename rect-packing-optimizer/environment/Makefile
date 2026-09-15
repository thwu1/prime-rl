CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -DNDEBUG
LDFLAGS = -lm
TARGET = solver
SRC = solver.cpp

.PHONY: all clean benchmark

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)

benchmark: $(TARGET)
	@bash /app/evaluate.sh
