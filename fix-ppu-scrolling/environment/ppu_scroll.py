"""
NES PPU Scroll/Address Register State Machine

Implements the NES PPU's internal register state machine controlling
VRAM addressing and background scroll position. Models four internal
registers (v, t, x, w) and their interactions with CPU-accessible
PPU registers.

Register layout for v and t (15 bits):
    yyy NN YYYYY XXXXX
    ||| || ||||| +++++-- coarse X scroll (5 bits, 0-4)
    ||| || +++++-------- coarse Y scroll (5 bits, 5-9)
    ||| ++-------------- nametable select (2 bits, 10-11)
    +++----------------- fine Y scroll (3 bits, 12-14)
"""



class PPUScrollState:
    """Models the four PPU internal scroll/address registers."""

    def __init__(self):
        self.v = 0        # Current VRAM address (15 bits)
        self.t = 0        # Temporary VRAM address (15 bits)
        self.x = 0        # Fine X scroll (3 bits)
        self.w = 0        # First/second write toggle (1 bit)
        self.ppuctrl = 0  # Cached $2000 value for increment mode

    def write_ppuctrl(self, data):
        """
        $2000 (PPUCTRL) write.
        Copies nametable select bits from data[1:0] into t[11:10].

        t: ...GH.. ........ <- d: ......GH
        """
        self.t = (self.t & ~0x0C00) | ((data & 0x03) << 10)
        self.ppuctrl = data

    def read_ppustatus(self):
        """
        $2002 (PPUSTATUS) read.
        Clears the write toggle w.

        w: <- 0
        """
        self.w = 0

    def write_ppuscroll(self, data):
        """
        $2005 (PPUSCROLL) write.
        First write (w=0): coarse X -> t[4:0], fine X -> x[2:0].
        Second write (w=1): fine Y -> t[14:12], coarse Y -> t[9:5].

        First write:
            t: ....... ...ABCDE <- d: ABCDE...
            x:              FGH <- d: .....FGH
            w:                  <- 1

        Second write:
            t: FGH..AB CDE..... <- d: ABCDEFGH
            w:                  <- 0
        """
        if self.w == 0:
            # First write: horizontal scroll
            self.t = (self.t & ~0x001F) | ((data >> 3) & 0x1F)
            self.x = data & 0x07
            self.w = 1
        else:
            # Second write: vertical scroll
            # Clear coarse Y field, then set fine Y and coarse Y from data
            self.t = (self.t & ~0x03E0)
            self.t |= ((data & 0x07) << 12)          # fine Y: d[2:0] -> t[14:12]
            self.t |= (((data >> 3) & 0x1F) << 5)    # coarse Y: d[7:3] -> t[9:5]
            self.w = 0

    def write_ppuaddr(self, data):
        """
        $2006 (PPUADDR) write.
        First write (w=0): data[5:0] -> t[13:8], bit 14 cleared.
        Second write (w=1): data[7:0] -> t[7:0], then t copied to v.

        First write:
            t: .CDEFGH ........ <- d: ..CDEFGH
            t: Z...... ........ <- 0 (bit 14 cleared)
            w:                  <- 1

        Second write:
            t: ....... ABCDEFGH <- d: ABCDEFGH
            v: <...all bits...> <- t: <...all bits...>
            w:                  <- 0
        """
        if self.w == 0:
            # First write: set high byte of address in t
            self.t = (self.t & ~0x3F00) | ((data & 0x3F) << 8)
            self.w = 1
        else:
            # Second write: set low byte, then copy t to v
            self.t = (self.t & 0xFF00) | (data & 0xFF)
            self.v = self.t
            self.w = 0

    def increment_coarse_x(self):
        """
        Increment coarse X component of v with nametable wrapping.
        Bits 0-4 count 0..31 across one nametable. Overflow toggles
        bit 10 (horizontal nametable) and resets coarse X to 0.
        """
        if (self.v & 0x001F) == 31:
            self.v &= ~0x001F
            self.v ^= 0x0400    # switch horizontal nametable
        else:
            self.v += 1

    def increment_y(self):
        """
        Increment Y position in v. Fine Y (bits 14-12) increments first.
        When fine Y overflows past 7, coarse Y (bits 9-5) increments.
        At coarse Y == 29 (last tile row), wraps to 0 and toggles nametable.
        At coarse Y == 31 (in attribute data), wraps to 0 without toggle.
        """
        if (self.v & 0x7000) != 0x7000:
            self.v += 0x1000                        # increment fine Y
        else:
            self.v &= ~0x7000                       # fine Y = 0
            y = (self.v & 0x03E0) >> 5              # extract coarse Y
            if y == 29:
                y = 0
                self.v ^= 0x0400                    # switch nametable vertically
            elif y == 31:
                y = 0                               # coarse Y wraps, no switch
            else:
                y += 1
            self.v = (self.v & ~0x03E0) | (y << 5)  # put coarse Y back

    def copy_horizontal(self):
        """
        At dot 257 of each scanline: copy horizontal scroll bits from t to v.
        Transfers coarse X (bits 4-0) and horizontal nametable (bit 10).

        v: ....A.. ...BCDEF <- t: ....A.. ...BCDEF
        """
        self.v = (self.v & ~0x001F) | (self.t & 0x001F)

    def copy_vertical(self):
        """
        During dots 280-304 of pre-render scanline: copy vertical scroll
        bits from t to v. Transfers fine Y (14-12), vertical nametable (11),
        and coarse Y (9-5).

        v: GHIA.BC DEF..... <- t: GHIA.BC DEF.....
        """
        self.v = (self.v & ~0x7BE0) | (self.t & 0x7BE0)

    def get_tile_address(self):
        """
        Compute nametable tile address from current v.
        tile address = 0x2000 | (v & 0x0FFF)
        """
        return 0x2000 | (self.v & 0x0FFF)

    def get_attribute_address(self):
        """
        Compute attribute table address from current v.

        NN 1111 YYY XXX
        || |||| ||| +++-- high 3 bits of coarse X (x/4)
        || |||| +++------ high 3 bits of coarse Y (y/4)
        || ++++---------- attribute offset (960 bytes)
        ++--------------- nametable select
        """
        return (0x23C0
                | (self.v & 0x0C00)
                | ((self.v >> 2) & 0x38)
                | ((self.v >> 4) & 0x07))

    def access_ppudata(self, is_rendering=False):
        """
        $2007 (PPUDATA) access. Outside rendering: v increments by 1 or 32
        (based on PPUCTRL bit 2). During rendering: coarse X and Y increment.
        """
        if is_rendering:
            self.increment_coarse_x()
            self.increment_y()
        else:
            if self.ppuctrl & 0x04:
                self.v += 32
            else:
                self.v += 1
            self.v &= 0x7FFF

    def get_scroll_x(self):
        """Get full 9-bit pixel X scroll from v and x registers."""
        coarse_x = self.v & 0x001F
        nt_h = (self.v >> 10) & 1
        return (nt_h * 256) + (coarse_x * 8) + self.x

    def get_scroll_y(self):
        """Get full 9-bit pixel Y scroll from v register."""
        fine_y = (self.v >> 12) & 0x07
        coarse_y = (self.v >> 5) & 0x1F
        nt_v = (self.v >> 11) & 1
        return (nt_v * 240) + (coarse_y * 8) + fine_y

    def get_state(self):
        """Return current register state as a dict."""
        return {
            'v': self.v,
            't': self.t,
            'x': self.x,
            'w': self.w,
        }

    def set_state(self, v=None, t=None, x=None, w=None):
        """Directly set register values (for testing)."""
        if v is not None:
            self.v = v & 0x7FFF
        if t is not None:
            self.t = t & 0x7FFF
        if x is not None:
            self.x = x & 0x07
        if w is not None:
            self.w = w & 0x01


def simulate_register_writes(operations):
    """
    Process a sequence of PPU register operations and return final state.

    Each operation is a tuple: (name, [data])
    Supported: 'ppuctrl', 'ppustatus', 'ppuscroll', 'ppuaddr',
               'ppudata', 'ppudata_render', 'inc_coarse_x',
               'inc_y', 'copy_h', 'copy_v', 'set_state'
    """
    ppu = PPUScrollState()
    for op in operations:
        name = op[0]
        if name == 'ppuctrl':
            ppu.write_ppuctrl(op[1])
        elif name == 'ppustatus':
            ppu.read_ppustatus()
        elif name == 'ppuscroll':
            ppu.write_ppuscroll(op[1])
        elif name == 'ppuaddr':
            ppu.write_ppuaddr(op[1])
        elif name == 'ppudata':
            ppu.access_ppudata(is_rendering=False)
        elif name == 'ppudata_render':
            ppu.access_ppudata(is_rendering=True)
        elif name == 'inc_coarse_x':
            ppu.increment_coarse_x()
        elif name == 'inc_y':
            ppu.increment_y()
        elif name == 'copy_h':
            ppu.copy_horizontal()
        elif name == 'copy_v':
            ppu.copy_vertical()
        elif name == 'set_state':
            ppu.set_state(**op[1])
    return ppu
