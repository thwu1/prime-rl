CXX = g++
TSAN_CXX = clang++
CXXFLAGS = -O2 -fopenmp -std=c++17 -Wall
TSANFLAGS = -O1 -fopenmp -fsanitize=thread -std=c++17 -g -DSMALL_SIZE

PROGS = histogram jacobi knn_search lu_factor
TSAN = $(addsuffix _tsan,$(PROGS))

.PHONY: all tsan clean

all: $(PROGS)

tsan: $(TSAN)

%: src/%.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

%_tsan: src/%.cpp
	$(TSAN_CXX) $(TSANFLAGS) -o $@ $<

clean:
	rm -f $(PROGS) $(TSAN)
