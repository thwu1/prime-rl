# Yosys synthesis script for adder_pipe optimization
# Targets reduced logic depth for better timing

# Read Liberty library
read_liberty -lib /app/cells.lib

# Read RTL design
read_verilog /app/design.v

# Elaborate and synthesize
synth -top adder_pipe -flatten

# Map flip-flops to library DFFs
dfflibmap -liberty /app/cells.lib

# Technology mapping with ABC
abc -liberty /app/cells.lib

# Clean up
clean -purge
opt_clean

# Write optimized netlist
write_verilog -noattr /app/optimized_netlist.v

# Print statistics
stat -liberty /app/cells.lib
