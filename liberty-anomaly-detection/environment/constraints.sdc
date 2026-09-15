# Timing constraints for adder_pipe design
# Target: 45nm process, nominal corner, aggressive clock
create_clock -name clk -period 0.250 [get_ports clk]
set_input_delay -clock clk 0.050 [get_ports {a[*] b[*] rst_n}]
set_output_delay -clock clk 0.050 [get_ports {sum[*] cout}]
