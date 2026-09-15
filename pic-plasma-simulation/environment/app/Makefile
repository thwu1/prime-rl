CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared -lm

LIB_DIR = lib
SRC_DIR = src

all: $(LIB_DIR)/pic_kernels.so

$(LIB_DIR)/pic_kernels.so: $(SRC_DIR)/pic_kernels.c
	mkdir -p $(LIB_DIR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -rf $(LIB_DIR)/*.so

run_langmuir: $(LIB_DIR)/pic_kernels.so
	python3 run_langmuir.py

run_two_stream: $(LIB_DIR)/pic_kernels.so
	python3 run_two_stream.py

run_all: run_langmuir run_two_stream

plot: run_all
	gnuplot plot_phase_space.gp

.PHONY: all clean run_langmuir run_two_stream run_all plot
