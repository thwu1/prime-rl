CXX = g++
CXXFLAGS = -std=c++20 -Wall -Wextra -I include

TESTS = test_arithmetic test_variables test_functions test_power \
        test_comparisons test_ternary test_letbind test_constfold test_complex

.PHONY: all test clean

all: test

test: $(TESTS)
	@echo "All tests passed."

$(TESTS): %: tests/%.cpp include/compiler.hpp include/vm.hpp include/bytecode.hpp
	$(CXX) $(CXXFLAGS) -o $@ $<
	./$@
	@echo "  [PASS] $@"

clean:
	rm -f $(TESTS)
