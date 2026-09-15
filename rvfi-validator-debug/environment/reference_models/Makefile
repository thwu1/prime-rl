all: simulate

m_ref_sim: m_ref.v tb_m_ext.v
	iverilog -o m_ref_sim m_ref.v tb_m_ext.v

simulate: m_ref_sim
	vvp m_ref_sim

clean:
	rm -f m_ref_sim

.PHONY: all simulate clean
