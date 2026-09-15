#!/usr/bin/env python3
"""
Earthrise Graphics Processor Emulator — Reference Implementation

Faithfully replicates the pixel-level behavior of the Earthrise 2D graphics
processor's SystemVerilog drawing modules (draw_line.sv, draw_circle.sv,
draw_rectangle.sv, draw_triangle_fill.sv).

"""
import sys

WIDTH = 160
HEIGHT = 120


class Earthrise:
    def __init__(self):
        self.fb = bytearray(WIDTH * HEIGHT)
        self.coords = [0] * 8   # x0, y0, x1, y1, x2, y2, x3, y3
        self.colors = [0] * 4   # lca, lcb, fca, fcb

    def plot(self, x, y, c):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.fb[y * WIDTH + x] = c

    # ----- Drawing primitives matching hardware exactly -----

    def draw_line(self, x0, y0, x1, y1, color):
        """
        Matches draw_line.sv:
        - Swaps endpoints so ya <= yb (y increases downward)
        - Computes 'right' flag from swapped coordinates
        - dx = abs(xb - xa), dy = ya - yb (always <= 0)
        - Combined movx+movy handling with single err update
        """
        if y0 > y1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0

        right = x0 < x1
        dx = (x1 - x0) if right else (x0 - x1)
        dy = y0 - y1
        err = dx + dy

        x, y = x0, y0
        x_end, y_end = x1, y1

        while True:
            self.plot(x, y, color)
            if x == x_end and y == y_end:
                break

            movx = (2 * err >= dy)
            movy = (2 * err <= dx)

            if movx and movy:
                x += 1 if right else -1
                y += 1
                err += dy + dx
            elif movx:
                x += 1 if right else -1
                err += dy
            elif movy:
                y += 1
                err += dx

    def draw_circle(self, cx, cy, r, color):
        """
        Matches draw_circle.sv:
        - Initial state: xa = -r, ya = 0, err = 2 - 2r
        - Outputs 4 quadrant points per iteration
        - CALC_Y phase: saves err_tmp, conditionally updates ya and err
        - CALC_X phase: uses err_tmp and (possibly updated) err/ya to
          conditionally update xa and err
        - Terminates when xa reaches 0

        Non-blocking assignment semantics are critical:
        in CALC_Y, err uses the ORIGINAL ya (before ya += 1)
        in CALC_X, err uses the ORIGINAL xa (before xa += 1)
        """
        if r <= 0:
            if r == 0:
                self.plot(cx, cy, color)
            return

        xa = -r
        ya = 0
        err = 2 - 2 * r

        while True:
            # DRAW: output 4 quadrant points
            self.plot(cx - xa, cy + ya, color)
            self.plot(cx + xa, cy + ya, color)
            self.plot(cx + xa, cy - ya, color)
            self.plot(cx - xa, cy - ya, color)

            # CALC_Y: check termination, then update ya/err
            if xa == 0:
                break

            err_tmp = err
            if err <= ya:
                ya += 1
                err += 2 * ya + 1

            # CALC_X: conditionally update xa/err
            if err_tmp > xa or err > ya:
                xa += 1
                err += 2 * xa + 1

    def draw_rect(self, x0, y0, x1, y1, color):
        """
        Matches draw_rectangle.sv: draws 4 lines in specific order.
        Line 0: (x0,y0) -> (x1,y0)
        Line 1: (x1,y0) -> (x1,y1)
        Line 2: (x1,y1) -> (x0,y1)
        Line 3: (x0,y1) -> (x0,y0)
        """
        self.draw_line(x0, y0, x1, y0, color)
        self.draw_line(x1, y0, x1, y1, color)
        self.draw_line(x1, y1, x0, y1, color)
        self.draw_line(x0, y1, x0, y0, color)

    def draw_filled_rect(self, x0, y0, x1, y1, color):
        """Fill all pixels in the rectangular region (inclusive)."""
        lx, hx = min(x0, x1), max(x0, x1)
        ly, hy = min(y0, y1), max(y0, y1)
        for yy in range(ly, hy + 1):
            for xx in range(lx, hx + 1):
                self.plot(xx, yy, color)

    def draw_filled_triangle(self, x0, y0, x1, y1, x2, y2, color):
        """
        Matches draw_triangle_fill.sv:
        - Edge function rasterization with incremental half-plane evaluation
        - Iterates over bounding box testing point-in-triangle via three edge
          functions, each computed incrementally by adding step values
        - Handles both CW and CCW winding via cross product sign detection
        - Edge functions: e_ij(px,py) = (xj-xi)(py-yi) - (yj-yi)(px-xi)
          x-step a_ij = yi-yj, y-step b_ij = xj-xi
        - CCW: inside when all edge functions >= 0
        - CW:  inside when all edge functions <= 0
        """
        # Edge function step values
        sa01 = y0 - y1
        sa12 = y1 - y2
        sa20 = y2 - y0
        sb01 = x1 - x0
        sb12 = x2 - x1
        sb20 = x0 - x2

        # Bounding box
        bbx0 = min(x0, x1, x2)
        bby0 = min(y0, y1, y2)
        bbx1 = max(x0, x1, x2)
        bby1 = max(y0, y1, y2)

        # Winding order: CW if cross product < 0
        cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        cw = cross < 0

        # Initial edge function values at (bbx0, bby0)
        w0_init = (bbx0 - x0) * sa01 + (bby0 - y0) * sb01
        w1_init = (bbx0 - x1) * sa12 + (bby0 - y1) * sb12
        w2_init = (bbx0 - x2) * sa20 + (bby0 - y2) * sb20

        w0_row = w0_init
        w1_row = w1_init
        w2_row = w2_init

        for scan_y in range(bby0, bby1 + 1):
            w0 = w0_row
            w1 = w1_row
            w2 = w2_row
            for scan_x in range(bbx0, bbx1 + 1):
                if cw:
                    inside = w0 <= 0 and w1 <= 0 and w2 <= 0
                else:
                    inside = w0 >= 0 and w1 >= 0 and w2 >= 0
                if inside:
                    self.plot(scan_x, scan_y, color)
                w0 += sa01
                w1 += sa12
                w2 += sa20
            w0_row += sb01
            w1_row += sb12
            w2_row += sb20

    # ----- ISA Decoder & Executor -----

    def execute(self, instructions):
        pc = 0
        while pc < len(instructions):
            word = instructions[pc]
            pc += 1

            nib = (word >> 12) & 0xF

            if nib <= 7:
                # Coordinate register load
                val = word & 0xFFF
                if val & 0x800:
                    val -= 0x1000
                self.coords[nib] = val

            elif nib == 0xC:
                sub = (word >> 8) & 0xF
                if sub == 0xE:
                    break
                elif sub <= 3:
                    self.colors[sub] = word & 0xFF

            elif nib == 0xD:
                shape = (word >> 8) & 0xF
                flags = word & 0xFF
                fill = bool(flags & 1)
                use_b = bool(flags & 2)

                if fill:
                    color = self.colors[2 + (1 if use_b else 0)]
                else:
                    color = self.colors[0 + (1 if use_b else 0)]

                x0 = self.coords[0]
                y0 = self.coords[1]
                x1 = self.coords[2]
                y1 = self.coords[3]
                x2 = self.coords[4]
                y2 = self.coords[5]

                if shape == 0:      # PIXEL
                    self.plot(x0, y0, color)
                elif shape == 1:    # LINE
                    self.draw_line(x0, y0, x1, y1, color)
                elif shape == 2:    # TRIANGLE
                    if fill:
                        self.draw_filled_triangle(x0, y0, x1, y1, x2, y2, color)
                    else:
                        self.draw_line(x0, y0, x1, y1, color)
                        self.draw_line(x1, y1, x2, y2, color)
                        self.draw_line(x2, y2, x0, y0, color)
                elif shape == 3:    # RECTANGLE
                    if fill:
                        self.draw_filled_rect(x0, y0, x1, y1, color)
                    else:
                        self.draw_rect(x0, y0, x1, y1, color)
                elif shape == 4:    # CIRCLE
                    self.draw_circle(x0, y0, x1, color)


def load_hex(path):
    """Load hex instruction file: one 4-digit hex per line, # comments."""
    instructions = []
    with open(path) as f:
        for line in f:
            line = line.split('#')[0].strip()
            if line:
                instructions.append(int(line, 16))
    return instructions


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.hex> <output.raw>", file=sys.stderr)
        sys.exit(1)

    instructions = load_hex(sys.argv[1])
    emu = Earthrise()
    emu.execute(instructions)

    with open(sys.argv[2], 'wb') as f:
        f.write(emu.fb)


if __name__ == '__main__':
    main()
