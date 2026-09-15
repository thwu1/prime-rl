# Element-wise ReLU: output[i] = max(0, x[i]) for 32-element vector
# Demonstrates vector-scalar operations and tiled processing
# Memory layout:
#   0:  x[0:31]      (input, 32 floats)
#   32: output[0:31]  (output, 32 floats)

ASET a0, 0          # input base
ASET a1, 32         # output base
SSET s0, 0.0        # zero constant

# Tile 0: elements 0-15
VLOAD v0, a0, 0     # x[0:15]
VFILL v1, s0        # vector of zeros
VMAX v2, v0, v1     # max(0, x)
VSTORE v2, a1, 0    # store result

# Tile 1: elements 16-31
VLOAD v0, a0, 16    # x[16:31]
VMAX v2, v0, v1     # max(0, x)  (v1 still holds zeros)
VSTORE v2, a1, 16   # store result

HALT
