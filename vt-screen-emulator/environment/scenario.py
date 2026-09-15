#!/usr/bin/env python3
"""
VT-420 Terminal Screen Buffer Test Scenario

Exercises a VTEmulator implementation through 8 phases of VT terminal
operations and records DECRQCRA checksums to /app/checksums.txt.

The emulator must use NUL (0) for uninitialized/erased cells.
DECRQCRA computes the 16-bit sum (mod 65536) of character ordinal
values within the specified rectangle.
"""

from vt_emulator import VTEmulator


def main():
    emu = VTEmulator(cols=80, rows=24)
    checksums = []

    # ================================================================
    # Phase 1: Basic character output
    # Write an 8x8 character grid at the top-left corner.
    # This is the same grid used by esctest2's rectangle operation tests.
    # ================================================================
    emu.cup(1, 1)
    emu.write("abcdefgh")
    emu.cup(2, 1)
    emu.write("ijklmnop")
    emu.cup(3, 1)
    emu.write("qrstuvwx")
    emu.cup(4, 1)
    emu.write("yz012345")
    emu.cup(5, 1)
    emu.write("ABCDEFGH")
    emu.cup(6, 1)
    emu.write("IJKLMNOP")
    emu.cup(7, 1)
    emu.write("QRSTUVWX")
    emu.cup(8, 1)
    emu.write("YZ6789!@")

    # Checkpoint 1: checksum of the 8x8 block
    checksums.append(emu.decrqcra(1, 1, 8, 8))

    # ================================================================
    # Phase 2: DECCRA -- non-overlapping copy
    # Copy the 3x3 block at rows 2-4, cols 2-4 to destination (5,5).
    # Source block: j k l / r s t / z 0 1
    # These values replace E F G / M N O / U V W at rows 5-7, cols 5-7.
    # ================================================================
    emu.deccra(src_top=2, src_left=2, src_bottom=4, src_right=4,
               src_page=1, dst_top=5, dst_left=5, dst_page=1)

    checksums.append(emu.decrqcra(1, 1, 8, 8))

    # ================================================================
    # Phase 3: DECCRA -- overlapping copy (requires snapshot semantics)
    # Restore the original 8x8 pattern, then copy source (2,2)-(4,4)
    # to destination (3,3). The source and destination rectangles overlap,
    # so the implementation must snapshot the source region BEFORE writing
    # to the destination.
    # ================================================================
    emu.cup(1, 1); emu.write("abcdefgh")
    emu.cup(2, 1); emu.write("ijklmnop")
    emu.cup(3, 1); emu.write("qrstuvwx")
    emu.cup(4, 1); emu.write("yz012345")
    emu.cup(5, 1); emu.write("ABCDEFGH")
    emu.cup(6, 1); emu.write("IJKLMNOP")
    emu.cup(7, 1); emu.write("QRSTUVWX")
    emu.cup(8, 1); emu.write("YZ6789!@")

    emu.deccra(src_top=2, src_left=2, src_bottom=4, src_right=4,
               src_page=1, dst_top=3, dst_left=3, dst_page=1)

    checksums.append(emu.decrqcra(1, 1, 8, 8))

    # ================================================================
    # Phase 4: DECSTBM scroll region + IND (Index)
    # Clear screen, write 6 labeled rows, set scroll region to rows 2-5,
    # position cursor at the bottom of the region, and issue IND.
    # The region scrolls up: row 2 content is lost, rows 3-5 shift up
    # by one, and a blank line appears at the bottom of the region.
    # Rows 1 and 6 (outside the region) are unaffected.
    # ================================================================
    emu.ed(2)
    emu.cup(1, 1); emu.write("TOP-LINE")
    emu.cup(2, 1); emu.write("LINE-TWO")
    emu.cup(3, 1); emu.write("LINE-THR")
    emu.cup(4, 1); emu.write("LINE-FOU")
    emu.cup(5, 1); emu.write("LINE-FIV")
    emu.cup(6, 1); emu.write("BOTTOM-L")

    emu.decstbm(2, 5)
    emu.cup(5, 1)
    emu.ind()
    emu.decstbm()

    checksums.append(emu.decrqcra(1, 1, 6, 8))

    # ================================================================
    # Phase 5: DECFRA -- fill rectangular area
    # Fill rows 2-4, cols 3-6 with '*' (0x2A). This overwrites part of
    # the text that was shifted during Phase 4's scroll.
    # ================================================================
    emu.decfra(ord('*'), 2, 3, 4, 6)

    checksums.append(emu.decrqcra(1, 1, 6, 8))

    # ================================================================
    # Phase 6: DECOM -- Origin Mode
    # Set scroll region rows 2-5 again, enable origin mode, and write
    # "ORIGIN" at CUP(1,1). In origin mode, row 1 maps to the top of
    # the scroll region (row 2 in absolute coordinates). The write
    # overwrites the first 6 columns of row 2.
    # ================================================================
    emu.decstbm(2, 5)
    emu.decset_decom()
    emu.cup(1, 1)
    emu.write("ORIGIN")
    emu.decreset_decom()
    emu.decstbm()

    checksums.append(emu.decrqcra(1, 1, 6, 8))

    # ================================================================
    # Phase 7: RI -- Reverse Index at top of scroll region
    # Clear screen, write 5 labeled rows, set scroll region to rows 2-4,
    # position cursor at the top of the region, and issue RI.
    # The region scrolls down: row 4 content is lost, rows 2-3 shift
    # down by one, and a blank line appears at the top of the region.
    # ================================================================
    emu.ed(2)
    emu.cup(1, 1); emu.write("ROW-1---")
    emu.cup(2, 1); emu.write("ROW-2---")
    emu.cup(3, 1); emu.write("ROW-3---")
    emu.cup(4, 1); emu.write("ROW-4---")
    emu.cup(5, 1); emu.write("ROW-5---")

    emu.decstbm(2, 4)
    emu.cup(2, 1)
    emu.ri()
    emu.decstbm()

    checksums.append(emu.decrqcra(1, 1, 5, 8))

    # ================================================================
    # Phase 8: DECERA -- erase rectangular area
    # Clear screen, write a 4x8 pattern, then erase the rectangle at
    # rows 2-3, cols 3-6 (set those cells back to NUL/0).
    # ================================================================
    emu.ed(2)
    emu.cup(1, 1); emu.write("AABBCCDD")
    emu.cup(2, 1); emu.write("EEFFGGHH")
    emu.cup(3, 1); emu.write("IIJJKKLL")
    emu.cup(4, 1); emu.write("MMNNOOPP")

    emu.decera(2, 3, 3, 6)

    checksums.append(emu.decrqcra(1, 1, 4, 8))

    # ================================================================
    # Write all checksums
    # ================================================================
    with open("/app/checksums.txt", "w") as f:
        for i, cs in enumerate(checksums):
            f.write("{}:{}\n".format(i + 1, cs))

    print("Checksums written to /app/checksums.txt")
    for i, cs in enumerate(checksums):
        print("  Checkpoint {}: {}".format(i + 1, cs))


if __name__ == "__main__":
    main()
