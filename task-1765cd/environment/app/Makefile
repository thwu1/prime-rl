CXX = g++
CXXFLAGS = -std=c++20 -Wall -Wextra -Wpedantic
LDFLAGS = -pthread
BUILD_DIR = build

.PHONY: all clean stress_test stress_test_tsan benchmark

all: stress_test stress_test_tsan benchmark

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

stress_test: $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -O2 -g $(LDFLAGS) -I include -o $(BUILD_DIR)/stress_test src/stress_test.cpp

stress_test_tsan: $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -O1 -g -fsanitize=thread $(LDFLAGS) -I include -o $(BUILD_DIR)/stress_test_tsan src/stress_test.cpp

benchmark: $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -O2 $(LDFLAGS) -I include -o $(BUILD_DIR)/benchmark src/benchmark.cpp

clean:
	rm -rf $(BUILD_DIR)
