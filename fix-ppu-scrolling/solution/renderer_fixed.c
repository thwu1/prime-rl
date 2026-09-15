/*
 * NES PPU Background Tile Renderer — corrected version
 *
 * Four bugs fixed relative to the original renderer.c:
 *   1. resolve_nt(): vertical mirroring uses nt & 1 (not (nt >> 1) & 1)
 *   2. inc_y(): coarse Y == 31 wraps without toggling nametable
 *   3. do_scanline(): bitplane order is (hb << 1) | lb (not (lb << 1) | hb)
 *   4. do_scanline(): attribute shift is ((cy & 2) << 1) | (cx & 2)
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>

#define FRAME_W     256
#define FRAME_H     240
#define FRAME_SIZE  (FRAME_W * FRAME_H)
#define CHR_SIZE    4096
#define VRAM_SIZE   2048
#define PAL_SIZE    32
#define MAX_REGIONS 8

typedef struct {
    int start_sl, end_sl;
    int scroll_x, scroll_y;
} Region;

typedef struct {
    char mirroring[32];
    int  pat_base;
    int  nregions;
    Region regions[MAX_REGIONS];
} Config;

static uint8_t chr[CHR_SIZE];
static uint8_t vram[VRAM_SIZE];
static uint8_t pal[PAL_SIZE];
static uint8_t fb[FRAME_SIZE];

static int read_bin(const char *path, uint8_t *buf, size_t sz) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    if (fread(buf, 1, sz, f) != sz) {
        fprintf(stderr, "%s: expected %zu bytes\n", path, sz);
        fclose(f); return -1;
    }
    fclose(f);
    return 0;
}

static int read_config(const char *path, Config *c) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return -1; }
    if (fscanf(f, "%31s", c->mirroring) != 1) goto err;
    if (fscanf(f, "%d", &c->pat_base) != 1)   goto err;
    if (fscanf(f, "%d", &c->nregions) != 1)    goto err;
    if (c->nregions > MAX_REGIONS) c->nregions = MAX_REGIONS;
    for (int i = 0; i < c->nregions; i++) {
        if (fscanf(f, "%d %d %d %d",
                   &c->regions[i].start_sl, &c->regions[i].end_sl,
                   &c->regions[i].scroll_x, &c->regions[i].scroll_y) != 4)
            goto err;
    }
    fclose(f);
    return 0;
err:
    fprintf(stderr, "%s: parse error\n", path);
    fclose(f);
    return -1;
}

/* FIX 1: vertical mirroring maps by horizontal bit (nt & 1) */
static int resolve_nt(int nt_h, int nt_v, const char *mir) {
    int nt = (nt_v << 1) | nt_h;
    if (strcmp(mir, "vertical") == 0)
        return nt & 1;
    return (nt >> 1) & 1;
}

static void make_v(int sx, int sy, uint16_t *v, int *fx) {
    *fx = sx & 7;
    int cx = (sx >> 3) & 0x1F;
    int nh = (sx >> 8) & 1;
    int fy = sy & 7;
    int cy = (sy >> 3) & 0x1F;
    int nv = (sy >> 8) & 1;
    *v = (uint16_t)((fy << 12) | (nv << 11) | (nh << 10) | (cy << 5) | cx);
}

/* FIX 2: y == 31 wraps without toggling nametable */
static uint16_t inc_y(uint16_t v) {
    if ((v & 0x7000) != 0x7000) {
        v += 0x1000;
    } else {
        v &= ~0x7000;
        int y = (v & 0x03E0) >> 5;
        if (y == 29) {
            y = 0;
            v ^= 0x0800;
        } else if (y == 31) {
            y = 0;
        } else {
            y += 1;
        }
        v = (v & ~0x03E0) | (y << 5);
    }
    return v;
}

static void do_scanline(uint16_t v, int fx, const char *mir,
                        int pat_base, uint8_t *out) {
    int fy = (v >> 12) & 7;
    int nv = (v >> 11) & 1;
    int cy = (v >> 5) & 0x1F;
    int cx = v & 0x1F;
    int nh = (v >> 10) & 1;

    int px = 0, sb = fx;

    while (px < FRAME_W) {
        int phys = resolve_nt(nh, nv, mir);
        int ti = vram[phys * 1024 + cy * 32 + cx];

        int ai = (cy >> 2) * 8 + (cx >> 2);
        uint8_t ab = vram[phys * 1024 + 960 + ai];
        /* FIX 4: attribute shift needs ((cy & 2) << 1) not (cy & 2) */
        int sh = ((cy & 2) << 1) | (cx & 2);
        int pn = (ab >> sh) & 3;

        int ta = pat_base + ti * 16;
        uint8_t lo = chr[ta + fy];
        uint8_t hi = chr[ta + 8 + fy];

        for (int b = sb; b < 8 && px < FRAME_W; b++, px++) {
            int sa = 7 - b;
            int lb = (lo >> sa) & 1;
            int hb = (hi >> sa) & 1;
            /* FIX 3: high bitplane is bit 1 of colour */
            int c  = (hb << 1) | lb;
            out[px] = (c == 0) ? pal[0] : pal[pn * 4 + c];
        }
        sb = 0;

        if (++cx > 31) { cx = 0; nh ^= 1; }
    }
}

int main(void) {
    if (read_bin("chr_rom.bin", chr, CHR_SIZE)  < 0) return 1;
    if (read_bin("vram.bin",    vram, VRAM_SIZE) < 0) return 1;
    if (read_bin("palette.bin", pal,  PAL_SIZE)  < 0) return 1;

    Config cfg;
    if (read_config("render_config.txt", &cfg) < 0) return 1;

    for (int r = 0; r < cfg.nregions; r++) {
        uint16_t v;
        int fx;
        make_v(cfg.regions[r].scroll_x, cfg.regions[r].scroll_y, &v, &fx);
        for (int sl = cfg.regions[r].start_sl;
             sl <= cfg.regions[r].end_sl; sl++) {
            do_scanline(v, fx, cfg.mirroring, cfg.pat_base, &fb[sl * FRAME_W]);
            v = inc_y(v);
        }
    }

    mkdir("output", 0755);
    FILE *f = fopen("output/frame_0.bin", "wb");
    if (!f) { perror("output/frame_0.bin"); return 1; }
    fwrite(fb, 1, FRAME_SIZE, f);
    fclose(f);
    printf("Wrote %d bytes to output/frame_0.bin\n", FRAME_SIZE);
    return 0;
}
