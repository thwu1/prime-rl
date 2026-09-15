# Dot Product: result = dot(a, b) for 32-element vectors
# Demonstrates multi-tile processing and scalar reductions
# Memory layout:
#   0:  a[0:31]  (input, 32 floats)
#   32: b[0:31]  (input, 32 floats)
#   64: result   (output, 1 float)

ASET a0, 0          # base of a
ASET a1, 32         # base of b
ASET a2, 64         # output address

SSET s0, 0.0        # accumulator

# Tile 0: elements 0-15
VLOAD v0, a0, 0     # a[0:15]
VLOAD v1, a1, 0     # b[0:15]
VMUL v2, v0, v1     # element-wise product
VREDSUM s1, v2      # sum of tile products
SADD s0, s0, s1     # accumulate

# Tile 1: elements 16-31
VLOAD v0, a0, 16    # a[16:31]
VLOAD v1, a1, 16    # b[16:31]
VMUL v2, v0, v1
VREDSUM s1, v2
SADD s0, s0, s1

# Store result
SSTORE s0, a2, 0

HALT
