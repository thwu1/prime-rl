# Sanity check: vector addition
# Loads two vectors from memory, adds them, stores result
# Input: 16 floats at addr 0, 16 floats at addr 16
# Output: sum at addr 32
VLD v0, 0
VLD v1, 16
VADD v2, v0, v1
VST v2, 32
HALT
