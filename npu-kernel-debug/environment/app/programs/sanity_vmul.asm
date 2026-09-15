# Sanity check: vector element-wise multiplication
# Input: 16 floats at addr 0, 16 floats at addr 16
# Output: product at addr 32
VLD v0, 0
VLD v1, 16
VMUL v2, v0, v1
VST v2, 32
HALT
