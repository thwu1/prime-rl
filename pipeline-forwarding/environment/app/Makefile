IVERILOG = iverilog
VVP = vvp

SRC_DIR = src
TB_DIR = tb

SRCS = $(SRC_DIR)/maxicore32.v $(SRC_DIR)/memorystage1.v $(SRC_DIR)/registersstage2.v \
       $(SRC_DIR)/registers.v $(SRC_DIR)/alu.v $(SRC_DIR)/agu.v $(SRC_DIR)/businterface.v

TB_SRCS = $(TB_DIR)/maxicore32_tb.v $(TB_DIR)/memory.v $(TB_DIR)/led.v

all: test

compile:
	$(IVERILOG) -g2012 -I$(SRC_DIR) -I$(TB_DIR) -o maxicore32_tb.vvp $(SRCS) $(TB_SRCS)

test: compile
	$(VVP) maxicore32_tb.vvp

clean:
	rm -f *.vvp *.vcd

.PHONY: all compile test clean
