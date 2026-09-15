#!/usr/bin/env python3
"""Generate binary test case files for the nanobot trace simulator task.

"""
import os

def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(bytes(data))

# ── Case 1: Simple single-bot assembly ─────────────────────────────────
# R=3, single voxel at (1,0,1)
# Trace: Flip, SMove<0,0,1>, Fill<1,0,0>, SMove<0,0,-1>, Flip, Halt
# Expected: valid=True, energy=3538, steps=6, model_match=True

# Model: R=3. Bit for (1,0,1) = 1*9+0*3+1 = 10.
# Bit 10 -> byte 10//8=1 of bitarray, bit 10%8=2 -> 0x04
model1 = [0x03, 0x00, 0x04, 0x00, 0x00]

trace1 = [
    0xFD,        # Flip
    0x34, 0x10,  # SMove <0,0,1>: a=11(z), i=1+15=16
    0xB3,        # Fill <1,0,0>: nd=(1+1)*9+(0+1)*3+(0+1)=22
    0x34, 0x0E,  # SMove <0,0,-1>: a=11(z), i=-1+15=14
    0xFD,        # Flip
    0xFF,        # Halt
]

# ── Case 2: Multi-bot assembly with fission/fusion ─────────────────────
# R=4, voxels at (1,0,1) and (2,0,2)
# Uses Fission to create 2 bots, parallel Fill, then Fusion
# Expected: valid=True, energy=14144, steps=9, model_match=True

# Model: R=4. Bits: (1,0,1)=1*16+0+1=17, (2,0,2)=2*16+0+2=34
# Bit 17 -> byte 2 of bitarray, bit 1 -> 0x02
# Bit 34 -> byte 4 of bitarray, bit 2 -> 0x04
model2 = [0x04, 0x00, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x00]

trace2 = [
    0xFD,              # Step 1 (1 bot): Flip
    0xB5, 0x00,        # Step 2 (1 bot): Fission <1,0,0> m=0
    0x34, 0x10,        # Step 3 cmd1 (bot1): SMove <0,0,1>
    0xDC, 0x66,        # Step 3 cmd2 (bot2): LMove <1,0,0> <0,0,1>
    0xB3,              # Step 4 cmd1 (bot1): Fill <1,0,0>
    0x73,              # Step 4 cmd2 (bot2): Fill <0,0,1>
    0x34, 0x0E,        # Step 5 cmd1 (bot1): SMove <0,0,-1>
    0x34, 0x0E,        # Step 5 cmd2 (bot2): SMove <0,0,-1>
    0xFE,              # Step 6 cmd1 (bot1): Wait
    0x14, 0x0E,        # Step 6 cmd2 (bot2): SMove <-1,0,0>
    0xB7,              # Step 7 cmd1 (bot1): FusionP <1,0,0>
    0x26,              # Step 7 cmd2 (bot2): FusionS <-1,0,0>
    0xFD,              # Step 8 (1 bot): Flip
    0xFF,              # Step 9 (1 bot): Halt
]

# ── Case 3: Invalid trace (movement through filled voxel) ──────────────
# R=3, model has voxels at (1,0,1) AND (1,1,1) (2 voxels)
# Trace fills (1,0,1) then tries SMove through it -> error
# Expected: valid=False, energy=1775, steps=3, model_match=False

# Model: bits 10 and 13. Both in byte 1 of bitarray.
# Bit 10 -> bit 2 -> 0x04. Bit 13 -> bit 5 -> 0x20. Combined: 0x24
model3 = [0x03, 0x00, 0x24, 0x00, 0x00]

trace3 = [
    0xFD,        # Flip
    0x34, 0x10,  # SMove <0,0,1>
    0xB3,        # Fill <1,0,0> -> fills (1,0,1)
    0x14, 0x10,  # SMove <1,0,0> -> ERROR: region includes Full voxel (1,0,1)
    0xFD,        # (unreachable) Flip
    0xFF,        # (unreachable) Halt
]

write_bytes('/app/cases/case1/target.mdl', model1)
write_bytes('/app/cases/case1/trace.nbt', trace1)
write_bytes('/app/cases/case2/target.mdl', model2)
write_bytes('/app/cases/case2/trace.nbt', trace2)
write_bytes('/app/cases/case3/target.mdl', model3)
write_bytes('/app/cases/case3/trace.nbt', trace3)

print("Generated all test cases successfully.")
