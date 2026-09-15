CXX = g++
CXXFLAGS = -std=c++17 -O2 -pthread
TSAN_FLAGS = -std=c++17 -O1 -g -fsanitize=thread -pthread

.PHONY: all clean tsan

all: stress_test

stress_test: stress_test.cpp mpmc_queue.h backoff.h
	$(CXX) $(CXXFLAGS) -o $@ stress_test.cpp

stress_test_tsan: stress_test.cpp mpmc_queue.h backoff.h
	$(CXX) $(TSAN_FLAGS) -DITEMS_PER_PRODUCER=2000 -o $@ stress_test.cpp

tsan: stress_test_tsan

clean:
	rm -f stress_test stress_test_tsan
