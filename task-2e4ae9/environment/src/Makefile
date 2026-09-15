IVERILOG = iverilog
VVP     = vvp
YOSYS   = yosys

.PHONY: test_ripple test_kogge test_brent test_sklansky test_rosc test_all \
        synth_ripple synth_kogge synth_brent synth_sklansky synth_all clean

# ---- Functional tests ----

test_ripple:
	$(IVERILOG) -DTEST_RIPPLE -o sim_ripple tb/tb_adder.v rtl/ripple_carry_adder.v
	$(VVP) sim_ripple

test_kogge:
	$(IVERILOG) -DTEST_KOGGE -o sim_kogge tb/tb_adder.v rtl/kogge_stone_adder.v
	$(VVP) sim_kogge

test_brent:
	$(IVERILOG) -DTEST_BRENT -o sim_brent tb/tb_adder.v rtl/brent_kung_adder.v
	$(VVP) sim_brent

test_sklansky:
	$(IVERILOG) -DTEST_SKLANSKY -o sim_sklansky tb/tb_adder.v rtl/sklansky_adder.v
	$(VVP) sim_sklansky

test_rosc:
	$(IVERILOG) -o sim_rosc tb/tb_ring_osc.v rtl/ring_oscillator.v
	$(VVP) sim_rosc

test_all: test_ripple test_kogge test_brent test_sklansky test_rosc

# ---- Yosys synthesis ----

synth_ripple:
	mkdir -p results
	echo "read_verilog rtl/ripple_carry_adder.v; synth -top ripple_carry_adder; tee -o results/ripple_carry_adder_synth.log stat" | $(YOSYS) -s -

synth_kogge:
	mkdir -p results
	echo "read_verilog rtl/kogge_stone_adder.v; synth -top kogge_stone_adder; tee -o results/kogge_stone_adder_synth.log stat" | $(YOSYS) -s -

synth_brent:
	mkdir -p results
	echo "read_verilog rtl/brent_kung_adder.v; synth -top brent_kung_adder; tee -o results/brent_kung_adder_synth.log stat" | $(YOSYS) -s -

synth_sklansky:
	mkdir -p results
	echo "read_verilog rtl/sklansky_adder.v; synth -top sklansky_adder; tee -o results/sklansky_adder_synth.log stat" | $(YOSYS) -s -

synth_all: synth_ripple synth_kogge synth_brent synth_sklansky

clean:
	rm -f sim_* *.vcd
	rm -rf results
