/* decode_png.c — Minimal PNG-to-raw-pixels decoder (incomplete)
 *
 * Build:  make  (or: gcc -Wall -O2 -std=c99 -o decode_png decode_png.c)
 * Usage:  ./decode_png input.png output.raw
 *
 * Writes raw pixel data: row-major, no padding, 8 bits per channel,
 * channel order matches color type  (G / GA / RGB / RGBA).
 *
 * INCOMPLETE — search for TODO to find missing functionality.
 * WARNING — some provided constants or logic may also contain errors.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  CRC-32  (ISO 3309 / ITU-T V.42, same polynomial as PNG)          */
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
    int      ch;           /* derived channel count */
} Hdr;

static int read_ihdr(const uint8_t *d, uint32_t len, Hdr *h) {
    if (len < 13) return -1;
    h->w = get32(d); h->h = get32(d + 4);
    h->depth = d[8]; h->ctype = d[9];
    if (d[10] || d[11])  return -1;        /* only method 0 / filter 0 */
    if (d[12])           return -1;        /* interlace not supported   */
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
/*  Bit reader  (LSB-first, as DEFLATE requires)                      */
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

/* Bit-reversal helpers */
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
    uint16_t fc[16];           /* firstcode   per bit-length  */
    int      mc[17];           /* maxcode     per bit-length  */
    uint16_t fs[16];           /* firstsymbol per bit-length  */
    uint8_t  sz[HF_MAX];
    uint16_t val[HF_MAX];
} HTab;

/* TODO: Build canonical Huffman decoding table from code lengths.
 *       lengths[i] = bit-length assigned to symbol i  (0 = unused).
 *       Must populate fast-lookup table and slow-path structures.
 *       Return 0 on success, -1 on error. */
static int htab_build(HTab *t, const uint8_t *lengths, int nsyms) {
    (void)t; (void)lengths; (void)nsyms;
    fprintf(stderr, "htab_build: not implemented\n");
    return -1;
}

/* TODO: Decode one symbol using the Huffman table.
 *       Return decoded symbol (>= 0) or -1 on error. */
static int htab_dec(Bits *br, const HTab *t) {
    (void)br; (void)t;
    fprintf(stderr, "htab_dec: not implemented\n");
    return -1;
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
    1,2,3,4,6,7,9,13,17,25,33,49,65,97,129,193,
    257,385,513,769,1025,1537,2049,3073,4097,6145,
    8193,12289,16385,24577
};
static const int DIST_EXTRA[30] = {
    0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,
    7,7,8,8,9,9,10,10,11,11,12,12,13,13
};
/* Code-length alphabet order in dynamic Huffman header */
static const int CL_ORDER[19] = {
    16,17,18,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
};

/* ------------------------------------------------------------------ */
/*  DEFLATE inflate                                                   */
/* ------------------------------------------------------------------ */

/* TODO: Decode a Huffman-compressed DEFLATE block (btype 1 or 2).
 *       Read literal/length symbols from hl:
 *         sym < 256  -> literal byte, append to output
 *         sym == 256 -> end of block
 *         sym 257-285 -> length code; read extra bits, then decode
 *                        distance symbol from hd with extra bits,
 *                        then copy <length> bytes from <distance>
 *                        back in the output.
 *       Return 0 on success, -1 on error. */
static int inflate_huff(Bits *br, Buf *ob,
                        const HTab *hl, const HTab *hd) {
    (void)br; (void)ob; (void)hl; (void)hd;
    fprintf(stderr, "inflate_huff: not implemented\n");
    return -1;
}

static int inflate_raw(Bits *br, Buf *ob) {
    int bfinal;
    do {
        bfinal = (int)bits_get(br, 1);
        int btype = (int)bits_get(br, 2);

        if (btype == 0) {
            /* Stored (uncompressed) block — byte-align the bit reader,
             * then copy raw data. */
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
            /* TODO: Fixed Huffman --
             * Build the default literal/length table (symbols 0-287):
             *   0-143   -> 8 bits, 144-255 -> 9 bits,
             *   256-279 -> 7 bits, 280-287 -> 8 bits.
             * Build the default distance table (symbols 0-31): all 5 bits.
             * Then decode with inflate_huff. */
            fprintf(stderr, "DEFLATE btype=1 (fixed Huffman) not implemented\n");
            return -1;

        } else if (btype == 2) {
            /* TODO: Dynamic Huffman --
             * Read HLIT (5 bits + 257), HDIST (5 bits + 1), HCLEN (4 bits + 4).
             * Read HCLEN 3-bit code-length codes in CL_ORDER[].
             * Build a code-length Huffman table, then use it to decode
             * HLIT + HDIST code lengths (handling repeat codes 16/17/18).
             * Build literal/length and distance tables, then decode. */
            fprintf(stderr, "DEFLATE btype=2 (dynamic Huffman) not implemented\n");
            return -1;

        } else {
            return -1;  /* reserved */
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
    if ((in[0] & 0x0F) != 8)  return -1;   /* CM must be 8 (deflate) */
    if (in[1] & 0x20)         return -1;   /* FDICT not supported     */

    Bits br;
    bits_init(&br, in + 2, ilen - 6);      /* skip 2-byte hdr, 4-byte checksum */

    Buf ob;
    if (buf_init(&ob, 1 << 16) < 0) return -1;
    if (inflate_raw(&br, &ob) < 0) { free(ob.d); return -1; }

    /* TODO: verify Adler-32 checksum stored in last 4 bytes of in[] */

    *out = ob.d; *olen = ob.n;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  PNG scanline defiltering                                          */
/* ------------------------------------------------------------------ */

/* TODO: Implement Paeth predictor per PNG specification.
 *       Given bytes a (left), b (above), c (upper-left),
 *       return the value closest to p = a + b - c. */
static uint8_t paeth(uint8_t a, uint8_t b, uint8_t c) {
    (void)a; (void)b; (void)c;
    return 0;    /* WRONG -- placeholder */
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

        if (ft == 0) {                      /* None */
            memcpy(row, s, stride);
        } else {
            /* TODO: implement filter types 1-4 (Sub, Up, Average, Paeth).
             * Currently just copies unfiltered -- WRONG for types 1-4. */
            memcpy(row, s, stride);
        }
        s += stride;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Library API  /  CLI main                                          */
/* ------------------------------------------------------------------ */

#ifdef BUILD_SHARED
#include "decode_png.h"

/* TODO: Wire up the library API to the internal decoding pipeline.
 *       Each function should decode PNG data and populate the
 *       PngImage struct with the resulting pixel data and metadata. */

int png_decode_file(const char *path, PngImage *img) {
    (void)path; (void)img;
    return -1;
}

int png_decode_memory(const uint8_t *data, size_t len, PngImage *img) {
    (void)data; (void)len; (void)img;
    return -1;
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

    /* Read entire file */
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END); long fsz = ftell(f); rewind(f);
    uint8_t *fd = (uint8_t *)malloc(fsz);
    if (!fd || (long)fread(fd, 1, fsz, f) != fsz) { fclose(f); return 1; }
    fclose(f);

    /* Verify PNG signature */
    static const uint8_t SIG[8] = {137,80,78,71,13,10,26,10};
    if (fsz < 8 || memcmp(fd, SIG, 8)) {
        fprintf(stderr, "Not a PNG file\n"); free(fd); return 1;
    }

    /* Walk chunks */
    Hdr hdr = {0};
    uint8_t *idat = NULL;
    size_t idatN = 0, idatC = 0;

    for (size_t p = 8; p + 12 <= (size_t)fsz; ) {
        uint32_t clen = get32(fd + p);
        if (p + 12 + clen > (size_t)fsz) break;

        uint32_t ecrc = get32(fd + p + 8 + clen);
        uint32_t acrc = crc32_buf(fd + p + 4, clen + 4);
        if (ecrc != acrc) {
            fprintf(stderr, "CRC error\n");
            free(fd); free(idat); return 1;
        }

        const uint8_t *ct = fd + p + 4;
        const uint8_t *cd = fd + p + 8;

        if (!memcmp(ct, "IHDR", 4)) {
            if (read_ihdr(cd, clen, &hdr) < 0) {
                fprintf(stderr, "Bad IHDR\n");
                free(fd); free(idat); return 1;
            }
        } else if (!memcmp(ct, "IDAT", 4)) {
            if (idatN + clen > idatC) {
                idatC = (idatN + clen) * 2;
                if (idatC < 4096) idatC = 4096;
                uint8_t *t = (uint8_t *)realloc(idat, idatC);
                if (!t) { free(fd); free(idat); return 1; }
                idat = t;
            }
            memcpy(idat + idatN, cd, clen);
            idatN += clen;
        } else if (!memcmp(ct, "IEND", 4)) {
            break;
        }
        p += 12 + clen;
    }

    if (!idat || !idatN) {
        fprintf(stderr, "No IDAT data found\n");
        free(fd); free(idat); return 1;
    }

    /* Inflate compressed IDAT stream */
    uint8_t *raw = NULL;
    size_t rawN = 0;
    if (inflate_zlib(idat, idatN, &raw, &rawN) < 0) {
        fprintf(stderr, "Inflate failed\n");
        free(fd); free(idat); return 1;
    }

    /* Reconstruct scanlines */
    int bpp = hdr.ch * (hdr.depth / 8);
    if (bpp < 1) bpp = 1;

    uint8_t *px = NULL;
    size_t pxN = 0;
    if (defilter(raw, rawN, hdr.w, hdr.h, bpp, &px, &pxN) < 0) {
        fprintf(stderr, "Defilter failed\n");
        free(fd); free(idat); free(raw); return 1;
    }

    /* Write raw pixels */
    FILE *fo = fopen(argv[2], "wb");
    if (!fo) {
        perror(argv[2]);
        free(fd); free(idat); free(raw); free(px); return 1;
    }
    fwrite(px, 1, pxN, fo);
    fclose(fo);

    free(fd); free(idat); free(raw); free(px);
    return 0;
}
#endif
