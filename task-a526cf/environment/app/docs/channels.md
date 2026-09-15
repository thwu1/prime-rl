# Notcurses Channel Encoding Reference

## 32-bit Single Channel

A single 32-bit channel encodes one color (either foreground or background):

```
Bit 31-30 : Alpha (2 bits) — NC_BG_ALPHA_MASK = 0x30000000
Bit 30    : (upper alpha bit)
Bit 29    : (lower alpha bit)
Bit 28    : Not-default flag — NC_BGDEFAULT_MASK = 0x40000000
            SET   → channel carries an explicit color (RGB or palette)
            CLEAR → channel uses the terminal's default color
Bit 27    : Palette flag — NC_BG_PALETTE = 0x08000000
            SET (with not-default) → palette-indexed color; index in bits 7-0
Bits 23-16: Red   component (8 bits)
Bits 15-8 : Green component (8 bits)
Bits  7-0 : Blue  component (8 bits)

Combined RGB mask: NC_BG_RGB_MASK = 0x00ffffff
```

### Channel type determination

```
channel_is_default(ch)    = !(ch & NC_BGDEFAULT_MASK)
channel_is_palindex(ch)   = !default && (ch & NC_BG_PALETTE)
channel_is_rgb(ch)        = !default && !palindex
```

### Alpha modes

| Value        | Constant             | Meaning                          |
|-------------|----------------------|----------------------------------|
| 0x00000000  | NCALPHA_OPAQUE       | Use this color; lock it in       |
| 0x10000000  | NCALPHA_BLEND        | Blend (average) with accumulated |
| 0x20000000  | NCALPHA_TRANSPARENT  | Skip — take color from below     |
| 0x30000000  | NCALPHA_HIGHCONTRAST | (FG only) Contrast against BG    |

HIGHCONTRAST is **forbidden** for background channels.

### Extracting components

```c
alpha = channel & NC_BG_ALPHA_MASK;          // e.g. 0x10000000
red   = (channel >> 16) & 0xff;
green = (channel >>  8) & 0xff;
blue  =  channel        & 0xff;
rgb24 =  channel & NC_BG_RGB_MASK;           // 24-bit packed
```

### Setting a channel to RGB

To construct a channel with OPAQUE alpha and RGB (r, g, b):

```c
channel = NC_BGDEFAULT_MASK | (r << 16) | (g << 8) | b;
```

To add a non-OPAQUE alpha (e.g. BLEND):

```c
channel = NC_BGDEFAULT_MASK | NCALPHA_BLEND | (r << 16) | (g << 8) | b;
```

Note: setting any alpha other than OPAQUE automatically requires the
not-default bit (NC_BGDEFAULT_MASK) to be set. A default channel always
has OPAQUE alpha.

## 64-bit Channel Pair

A 64-bit channel pair packs **foreground** in the upper 32 bits and
**background** in the lower 32 bits:

```
Bits 63-32 : foreground channel (+ some extra flag bits in 63, 58-56)
Bits 31-0  : background channel
```

### Extracting channels from the pair

The upper bits (63, 58-56) carry rendering-optimization flags
(NC_NOBACKGROUND_MASK = 0x8700000000000000) that are **not** part of
the color/alpha data. Strip them when extracting:

```c
uint32_t bchannel(uint64_t channels) {
    return (uint32_t)(channels) & NC_CHANNEL_MASK;
}
uint32_t fchannel(uint64_t channels) {
    return bchannel(channels >> 32u);
}
```

where `NC_CHANNEL_MASK = NC_BG_ALPHA_MASK | NC_BGDEFAULT_MASK | NC_BG_PALETTE | NC_BG_RGB_MASK = 0x78ffffff`.

### Common channel pair values

| Description                  | FG channel   | BG channel   | 64-bit pair          |
|-----------------------------|-------------|-------------|---------------------|
| FG=red opaque, BG=green opaque  | 0x40ff0000  | 0x4000ff00  | 0x40ff00004000ff00  |
| FG=transparent, BG=transparent  | 0x60000000  | 0x60000000  | 0x6000000060000000  |
| FG=blend red, BG=opaque black   | 0x50ff0000  | 0x40000000  | 0x50ff000040000000  |
| FG=highcontrast, BG=opaque white| 0x70000000  | 0x40ffffff  | 0x7000000040ffffff  |
| FG=default, BG=default          | 0x00000000  | 0x00000000  | 0x0000000000000000  |
