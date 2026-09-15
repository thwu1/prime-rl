# Vector Addition: output = a + b (16-element vectors)
# Memory layout:
#   0:  a[0:15]      (input, 16 floats)
#   16: b[0:15]      (input, 16 floats)
#   32: output[0:15] (output, 16 floats)

ASET a0, 0
ASET a1, 32

VLOAD v0, a0, 0     # load a
VLOAD v1, a0, 16    # load b
VADD v2, v0, v1     # output = a + b
VSTORE v2, a1, 0    # store output

HALT
