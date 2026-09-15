/* decode_png_complete.c — Complete PNG-to-raw-pixels decoder
 *
 * Build:  gcc -Wall -O2 -std=c99 -o decode_png decode_png_complete.c
 * Usage:  ./decode_png input.png output.raw
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  CRC-32                                                            */
/* ------------------------------------------------------------------ */
static uint32_t crc_tab[256];
static int crc_ready;

static void crc_init(void) {
    for (unsigned n = 0; n < 256; n++) {
        uint32_t c = n;
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (c & 1 ? 0xEDB88320u : 0);
        crc_tab[n] = c;
    }
    crc_ready = 1;
}

static uint32_t crc32_buf(const uint8_t *buf, size_t len) {
    if (!crc_ready) crc_init();
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++)
        c = crc_tab[(c ^ buf[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */
static uint32_t get32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] <<  8) |  (uint32_t)p[3];
}

/* ------------------------------------------------------------------ */
/*  PNG IHDR                                                          */
/* ------------------------------------------------------------------ */
typedef struct {
    uint32_t w, h;
    uint8_t  depth, ctype;
    int      ch;
} Hdr;

static int read_ihdr(const uint8_t *d, uint32_t len, Hdr *h) {
    if (len < 13) return -1;
    h->w = get32(d); h->h = get32(d + 4);
    h->depth = d[8]; h->ctype = d[9];
    if (d[10] || d[11])  return -1;
    if (d[12])           return -1;
    switch (h->ctype) {
        case 0: h->ch = 1; break;
        case 2: h->ch = 3; break;
        case 4: h->ch = 2; break;
        case 6: h->ch = 4; break;
        default: return -1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Growable output buffer                                            */
/* ------------------------------------------------------------------ */
typedef struct { uint8_t *d; size_t n, cap; } Buf;

static int buf_init(Buf *b, size_t c) {
    b->d = (uint8_t *)malloc(c); b->n = 0; b->cap = c;
    return b->d ? 0 : -1;
}
static int buf_need(Buf *b, size_t extra) {
    if (b->n + extra <= b->cap) return 0;
    size_t nc = b->cap * 2;
    if (nc < b->n + extra) nc = b->n + extra;
    uint8_t *p = (uint8_t *)realloc(b->d, nc);
    if (!p) return -1;
    b->d = p; b->cap = nc;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Bit reader  (LSB-first)                                           */
/* ------------------------------------------------------------------ */
typedef struct {
    const uint8_t *src;
    size_t len, pos;
    uint32_t bits;
    int nb;
} Bits;

static void bits_init(Bits *b, const uint8_t *s, size_t l) {
    b->src = s; b->len = l; b->pos = 0;
    b->bits = 0; b->nb = 0;
}
static void bits_fill(Bits *b) {
    while (b->nb <= 24 && b->pos < b->len) {
        b->bits |= (uint32_t)b->src[b->pos++] << b->nb;
        b->nb += 8;
    }
}
static uint32_t bits_get(Bits *b, int n) {
    if (n == 0) return 0;
    bits_fill(b);
    uint32_t v = b->bits & ((1u << n) - 1);
    b->bits >>= n; b->nb -= n;
    return v;
}

static uint16_t bitrev16(uint16_t n) {
    n = ((n & 0xAAAA) >> 1) | ((n & 0x5555) << 1);
    n = ((n & 0xCCCC) >> 2) | ((n & 0x3333) << 2);
    n = ((n & 0xF0F0) >> 4) | ((n & 0x0F0F) << 4);
    return (uint16_t)((n >> 8) | (n << 8));
}
static uint16_t bitrev(uint16_t v, int nbits) {
    return bitrev16(v) >> (16 - nbits);
}

/* ------------------------------------------------------------------ */
/*  Huffman table                                                     */
/* ------------------------------------------------------------------ */
#define HF_FAST 9
#define HF_MAX  288

typedef struct {
    uint16_t fast[1 << HF_FAST];
    uint16_t fc[16];
    int      mc[17];
    uint16_t fs[16];
    uint8_t  sz[HF_MAX];
    uint16_t val[HF_MAX];
} HTab;

static int htab_build(HTab *t, const uint8_t *lengths, int nsyms) {
    int i, k = 0, code;
    int sizes[17];
    int next_code[16];

    memset(sizes, 0, sizeof(sizes));
    memset(t->fast, 0, sizeof(t->fast));
    memset(t->sz,  0, sizeof(t->sz));
    memset(t->val, 0, sizeof(t->val));

    for (i = 0; i < nsyms; i++)
        if (lengths[i] < 16) sizes[lengths[i]]++;
    sizes[0] = 0;

    code = 0;
    for (i = 1; i < 16; i++) {
        next_code[i] = code;
        t->fc[i] = (uint16_t)code;
        t->fs[i] = (uint16_t)k;
        code += sizes[i];
        if (sizes[i] && code - 1 >= (1 << i))
            return -1;
        t->mc[i] = code << (16 - i);
        code <<= 1;
        k += sizes[i];
    }
    t->mc[16] = 0x10000;

    for (i = 0; i < nsyms; i++) {
        int s = lengths[i];
        if (s) {
            int c = next_code[s] - t->fc[s] + t->fs[s];
            if (c < 0 || c >= HF_MAX) return -1;
            t->sz[c]  = (uint8_t)s;
            t->val[c] = (uint16_t)i;
            if (s <= HF_FAST) {
                uint16_t fv = (uint16_t)((s << 9) | i);
                int j = bitrev((uint16_t)next_code[s], s);
                while (j < (1 << HF_FAST)) {
                    t->fast[j] = fv;
                    j += (1 << s);
                }
            }
            next_code[s]++;
        }
    }
    return 0;
}

static int htab_dec(Bits *br, const HTab *t) {
    bits_fill(br);

    /* Fast path: 9-bit direct lookup */
    uint16_t fv = t->fast[br->bits & ((1u << HF_FAST) - 1)];
    if (fv) {
        int s = fv >> 9;
        br->bits >>= s;
        br->nb -= s;
        return fv & 0x1FF;
    }

    /* Slow path: bit-reverse and compare against maxcode */
    int k = bitrev16((uint16_t)(br->bits & 0xFFFF));
    int s;
    for (s = HF_FAST + 1; s < 16; s++)
        if (k < t->mc[s]) break;
    if (s >= 16) return -1;

    int b = (k >> (16 - s)) - t->fc[s] + t->fs[s];
    if (b < 0 || b >= HF_MAX || t->sz[b] != (uint8_t)s) return -1;

    br->bits >>= s;
    br->nb -= s;
    return t->val[b];
}

/* ------------------------------------------------------------------ */
/*  DEFLATE constants                                                 */
/* ------------------------------------------------------------------ */
static const int LEN_BASE[29] = {
    3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,
    35,43,51,59,67,83,99,115,131,163,195,227,258
};
static const int LEN_EXTRA[29] = {
    0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,
    3,3,3,3,4,4,4,4,5,5,5,5,0
};
static const int DIST_BASE[30] = {
    1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,
    257,385,513,769,1025,1537,2049,3073,4097,6145,
    8193,12289,16385,24577
};
static const int DIST_EXTRA[30] = {
    0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,
    7,7,8,8,9,9,10,10,11,11,12,12,13,13
};
/* Correct code-length alphabet order per RFC 1951 section 3.2.7 */
static const int CL_ORDER[19] = {
    16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15
};

/* ------------------------------------------------------------------ */
/*  DEFLATE inflate                                                   */
/* ------------------------------------------------------------------ */
static int inflate_huff(Bits *br, Buf *ob,
                        const HTab *hl, const HTab *hd) {
    for (;;) {
        int sym = htab_dec(br, hl);
        if (sym < 0) return -1;

        if (sym < 256) {
            /* literal byte */
            if (buf_need(ob, 1) < 0) return -1;
            ob->d[ob->n++] = (uint8_t)sym;

        } else if (sym == 256) {
            return 0;   /* end of block */

        } else {
            /* length/distance pair */
            int li = sym - 257;
            if (li >= 29) return -1;
            int length = LEN_BASE[li] + (int)bits_get(br, LEN_EXTRA[li]);

            int di = htab_dec(br, hd);
            if (di < 0 || di >= 30) return -1;
            int dist = DIST_BASE[di] + (int)bits_get(br, DIST_EXTRA[di]);

            if ((size_t)dist > ob->n) return -1;
            if (buf_need(ob, (size_t)length) < 0) return -1;

            /* byte-at-a-time copy handles overlapping references */
            for (int i = 0; i < length; i++)
                ob->d[ob->n + i] = ob->d[ob->n - dist + i];
            ob->n += (size_t)length;
        }
    }
}

static int inflate_raw(Bits *br, Buf *ob) {
    int bfinal;
    do {
        bfinal = (int)bits_get(br, 1);
        int btype = (int)bits_get(br, 2);

        if (btype == 0) {
            /* Stored block — byte-align, then copy raw data */
            br->pos -= (unsigned)br->nb / 8;
            br->bits = 0; br->nb = 0;
            if (br->pos + 4 > br->len) return -1;
            uint16_t slen  = br->src[br->pos]     |
                             ((uint16_t)br->src[br->pos + 1] << 8);
            uint16_t nlen  = br->src[br->pos + 2] |
                             ((uint16_t)br->src[br->pos + 3] << 8);
            br->pos += 4;
            if ((uint16_t)~nlen != slen) return -1;
            if (br->pos + slen > br->len) return -1;
            if (buf_need(ob, slen) < 0) return -1;
            memcpy(ob->d + ob->n, br->src + br->pos, slen);
            ob->n += slen; br->pos += slen;

        } else if (btype == 1) {
            /* Fixed Huffman */
            HTab hl, hd;
            uint8_t ll[288], dl[32];
            int i;
            for (i =   0; i <= 143; i++) ll[i] = 8;
            for (i = 144; i <= 255; i++) ll[i] = 9;
            for (i = 256; i <= 279; i++) ll[i] = 7;
            for (i = 280; i <= 287; i++) ll[i] = 8;
            if (htab_build(&hl, ll, 288) < 0) return -1;

            for (i = 0; i < 32; i++) dl[i] = 5;
            if (htab_build(&hd, dl, 32) < 0) return -1;

            if (inflate_huff(br, ob, &hl, &hd) < 0) return -1;

        } else if (btype == 2) {
            /* Dynamic Huffman */
            int hlit  = (int)bits_get(br, 5) + 257;
            int hdist = (int)bits_get(br, 5) + 1;
            int hclen = (int)bits_get(br, 4) + 4;

            uint8_t cl_lens[19];
            memset(cl_lens, 0, sizeof(cl_lens));
            for (int i = 0; i < hclen; i++)
                cl_lens[CL_ORDER[i]] = (uint8_t)bits_get(br, 3);

            HTab hcl;
            if (htab_build(&hcl, cl_lens, 19) < 0) return -1;

            int total = hlit + hdist;
            uint8_t all_lens[288 + 32];
            memset(all_lens, 0, sizeof(all_lens));

            int n = 0;
            while (n < total) {
                int sym = htab_dec(br, &hcl);
                if (sym < 0) return -1;

                if (sym < 16) {
                    all_lens[n++] = (uint8_t)sym;
                } else if (sym == 16) {
                    if (n == 0) return -1;
                    int rep = 3 + (int)bits_get(br, 2);
                    uint8_t prev = all_lens[n - 1];
                    for (int r = 0; r < rep && n < total; r++)
                        all_lens[n++] = prev;
                } else if (sym == 17) {
                    int rep = 3 + (int)bits_get(br, 3);
                    for (int r = 0; r < rep && n < total; r++)
                        all_lens[n++] = 0;
                } else if (sym == 18) {
                    int rep = 11 + (int)bits_get(br, 7);
                    for (int r = 0; r < rep && n < total; r++)
                        all_lens[n++] = 0;
                } else {
                    return -1;
                }
            }

            HTab hl, hd;
            if (htab_build(&hl, all_lens, hlit) < 0) return -1;
            if (htab_build(&hd, all_lens + hlit, hdist) < 0) return -1;
            if (inflate_huff(br, ob, &hl, &hd) < 0) return -1;

        } else {
            return -1;
        }
    } while (!bfinal);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  zlib wrapper                                                      */
/* ------------------------------------------------------------------ */
static int inflate_zlib(const uint8_t *in, size_t ilen,
                        uint8_t **out, size_t *olen) {
    if (ilen < 6) return -1;
    if (((in[0] * 256 + in[1]) % 31) != 0) return -1;
    if ((in[0] & 0x0F) != 8)  return -1;
    if (in[1] & 0x20)         return -1;

    Bits br;
    bits_init(&br, in + 2, ilen - 6);

    Buf ob;
    if (buf_init(&ob, 1 << 16) < 0) return -1;
    if (inflate_raw(&br, &ob) < 0) { free(ob.d); return -1; }

    /* Verify Adler-32 */
    uint32_t s1 = 1, s2 = 0;
    for (size_t i = 0; i < ob.n; i++) {
        s1 = (s1 + ob.d[i]) % 65521;
        s2 = (s2 + s1)      % 65521;
    }
    uint32_t computed = (s2 << 16) | s1;
    uint32_t expected = get32(in + ilen - 4);
    if (computed != expected) { free(ob.d); return -1; }

    *out = ob.d; *olen = ob.n;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  PNG scanline defiltering                                          */
/* ------------------------------------------------------------------ */
static uint8_t paeth(uint8_t a, uint8_t b, uint8_t c) {
    int p  = (int)a + (int)b - (int)c;
    int pa = p - (int)a; if (pa < 0) pa = -pa;
    int pb = p - (int)b; if (pb < 0) pb = -pb;
    int pc = p - (int)c; if (pc < 0) pc = -pc;
    if (pa <= pb && pa <= pc) return a;
    if (pb <= pc)             return b;
    return c;
}

static int defilter(const uint8_t *in, size_t ilen,
                    uint32_t w, uint32_t h, int bpp,
                    uint8_t **out, size_t *olen) {
    size_t stride = (size_t)w * bpp;
    *olen = stride * h;
    *out  = (uint8_t *)malloc(*olen);
    if (!*out) return -1;
    if (ilen < (stride + 1) * h) { free(*out); *out = NULL; return -1; }

    const uint8_t *s = in;
    for (uint32_t y = 0; y < h; y++) {
        uint8_t ft = *s++;
        uint8_t *row = *out + y * stride;
        const uint8_t *prev = (y > 0) ? (*out + (y - 1) * stride) : NULL;

        for (size_t k = 0; k < stride; k++) {
            uint8_t a = (k >= (size_t)bpp) ? row[k - bpp] : 0;
            uint8_t b = prev ? prev[k] : 0;
            uint8_t c = (prev && k >= (size_t)bpp) ? prev[k - bpp] : 0;
            uint8_t raw = s[k];

            switch (ft) {
                case 0: row[k] = raw;                                break;
                case 1: row[k] = (uint8_t)(raw + a);                break;
                case 2: row[k] = (uint8_t)(raw + b);                break;
                case 3: row[k] = (uint8_t)(raw + (((int)a+(int)b) >> 1)); break;
                case 4: row[k] = (uint8_t)(raw + paeth(a, b, c));   break;
                default: free(*out); *out = NULL; return -1;
            }
        }
        s += stride;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Common decode function                                            */
/* ------------------------------------------------------------------ */
static int decode_png_buf(const uint8_t *fd, size_t fsz,
                          uint8_t **out_px, uint32_t *out_w,
                          uint32_t *out_h, int *out_ch) {
    static const uint8_t SIG[8] = {137,80,78,71,13,10,26,10};
    if (fsz < 8 || memcmp(fd, SIG, 8)) return -1;

    Hdr hdr = {0};
    uint8_t *idat = NULL;
    size_t idatN = 0, idatC = 0;

    for (size_t p = 8; p + 12 <= fsz; ) {
        uint32_t clen = get32(fd + p);
        if (p + 12 + clen > fsz) break;

        uint32_t ecrc = get32(fd + p + 8 + clen);
        uint32_t acrc = crc32_buf(fd + p + 4, clen + 4);
        if (ecrc != acrc) { free(idat); return -1; }

        const uint8_t *ct = fd + p + 4;
        const uint8_t *cd = fd + p + 8;

        if (!memcmp(ct, "IHDR", 4)) {
            if (read_ihdr(cd, clen, &hdr) < 0) { free(idat); return -1; }
        } else if (!memcmp(ct, "IDAT", 4)) {
            if (idatN + clen > idatC) {
                idatC = (idatN + clen) * 2;
                if (idatC < 4096) idatC = 4096;
                uint8_t *t = (uint8_t *)realloc(idat, idatC);
                if (!t) { free(idat); return -1; }
                idat = t;
            }
            memcpy(idat + idatN, cd, clen);
            idatN += clen;
        } else if (!memcmp(ct, "IEND", 4)) {
            break;
        }
        p += 12 + clen;
    }

    if (!idat || !idatN) { free(idat); return -1; }

    uint8_t *raw = NULL;
    size_t rawN = 0;
    if (inflate_zlib(idat, idatN, &raw, &rawN) < 0) {
        free(idat); return -1;
    }
    free(idat);

    int bpp = hdr.ch * (hdr.depth / 8);
    if (bpp < 1) bpp = 1;

    uint8_t *px = NULL;
    size_t pxN = 0;
    if (defilter(raw, rawN, hdr.w, hdr.h, bpp, &px, &pxN) < 0) {
        free(raw); return -1;
    }
    free(raw);

    *out_px = px;
    *out_w = hdr.w;
    *out_h = hdr.h;
    *out_ch = hdr.ch;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Library API  /  CLI main                                          */
/* ------------------------------------------------------------------ */

#ifdef BUILD_SHARED
#include "decode_png.h"

int png_decode_file(const char *path, PngImage *img) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long fsz = ftell(f);
    rewind(f);
    uint8_t *fd = (uint8_t *)malloc(fsz);
    if (!fd) { fclose(f); return -1; }
    if ((long)fread(fd, 1, fsz, f) != fsz) { fclose(f); free(fd); return -1; }
    fclose(f);

    int ret = decode_png_buf(fd, (size_t)fsz,
                             &img->pixels, &img->width,
                             &img->height, &img->channels);
    free(fd);
    return ret;
}

int png_decode_memory(const uint8_t *data, size_t len, PngImage *img) {
    return decode_png_buf(data, len,
                          &img->pixels, &img->width,
                          &img->height, &img->channels);
}

void png_free(PngImage *img) {
    if (img) { free(img->pixels); img->pixels = NULL; }
}

#else

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s input.png output.raw\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END);
    long fsz = ftell(f);
    rewind(f);
    uint8_t *fd = (uint8_t *)malloc(fsz);
    if (!fd || (long)fread(fd, 1, fsz, f) != fsz) { fclose(f); return 1; }
    fclose(f);

    uint8_t *px = NULL;
    uint32_t w, h;
    int ch;
    if (decode_png_buf(fd, (size_t)fsz, &px, &w, &h, &ch) < 0) {
        fprintf(stderr, "Decode failed\n");
        free(fd);
        return 1;
    }
    free(fd);

    FILE *fo = fopen(argv[2], "wb");
    if (!fo) { perror(argv[2]); free(px); return 1; }
    fwrite(px, 1, (size_t)w * h * ch, fo);
    fclose(fo);
    free(px);
    return 0;
}
#endif
