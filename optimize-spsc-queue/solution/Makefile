CXX = g++
CXXFLAGS = -std=c++20 -O2 -Wall -Wextra -I include
LDFLAGS = -lpthread

.PHONY: all clean check stress

all: check

check:
	@echo '#include "spsc_queue.h"' > /tmp/_spsc_check.cpp
	@echo '#include "shm_protocol.h"' >> /tmp/_spsc_check.cpp
	@echo 'int main() { return 0; }' >> /tmp/_spsc_check.cpp
	$(CXX) $(CXXFLAGS) -o /tmp/_spsc_check /tmp/_spsc_check.cpp $(LDFLAGS)
	@rm -f /tmp/_spsc_check /tmp/_spsc_check.cpp
	@echo "Compilation check passed."

stress: stress_test.cpp
	$(CXX) $(CXXFLAGS) -o stress_test stress_test.cpp $(LDFLAGS)
	./stress_test

clean:
	@rm -f /tmp/_spsc_check /tmp/_spsc_check.cpp stress_test
