SRC_DIR = src
TB_DIR = tb
PROG_DIR = programs

CORE_SRCS = $(SRC_DIR)/maxicore32.v $(SRC_DIR)/memorystage1.v $(SRC_DIR)/registersstage2.v \
            $(SRC_DIR)/alu.v $(SRC_DIR)/agu.v $(SRC_DIR)/registers.v $(SRC_DIR)/businterface.v \
            $(SRC_DIR)/memory.v $(SRC_DIR)/led.v

TB_SRC = $(TB_DIR)/maxicore32_tb.v

.PHONY: sim clean

sim: $(CORE_SRCS) $(TB_SRC) program.hex
	iverilog -g2005-sv -I$(SRC_DIR) -o sim_out $(CORE_SRCS) $(TB_SRC)
	vvp sim_out

clean:
	rm -f sim_out program.hex *.vcd
