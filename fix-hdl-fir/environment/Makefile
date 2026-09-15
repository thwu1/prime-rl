VERILATOR   = verilator
TOP_MODULE  = fir_top
SV_SRCS     = src/fir_pkg.sv src/fir_engine.sv src/fir_top.sv
CPP_SRC     = sim/sim_main.cpp

.PHONY: lint build run clean

lint:
	$(VERILATOR) --lint-only --top-module $(TOP_MODULE) $(SV_SRCS)

build: clean
	$(VERILATOR) --cc --exe --build --top-module $(TOP_MODULE) $(SV_SRCS) $(CPP_SRC)

run: build
	./obj_dir/V$(TOP_MODULE)

clean:
	rm -rf obj_dir response_a.txt response_b.txt response_atomic.txt response_switch.txt latency.txt
