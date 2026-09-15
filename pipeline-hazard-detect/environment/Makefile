IVERILOG = iverilog -g 2012 -g io-range-error -Wall -I src
VVP = vvp

CORE_SRC = src/maxicore32.v src/businterface.v src/registers.v src/alu.v src/agu.v \
	src/memorystage1.v src/registersstage2.v \
	src/memory.v src/led.v

maxicore32_tb: $(CORE_SRC) tb/maxicore32_tb.v
	$(IVERILOG) -s maxicore32_tb -o $@ $^

clean:
	rm -f maxicore32_tb *.vcd maxicore32-ram-contents.txt

.PHONY: clean
