/* nacl_vault.c — Multi-recipient file encryption using TweetNaCl
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "tweetnacl.h"

#define CHUNK_SIZE   65536
#define HEADER_SIZE  40
#define RECIP_SIZE   104
#define MAX_RECIP    256

/* ── Little-endian helpers ─────────────────────────────────────────────── */

static void put_u16le(unsigned char *p, uint16_t v) {
    p[0] = v & 0xff;
    p[1] = (v >> 8) & 0xff;
}
static uint16_t get_u16le(const unsigned char *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static void put_u64le(unsigned char *p, uint64_t v) {
    for (int i = 0; i < 8; i++) { p[i] = (v >> (8*i)) & 0xff; }
}
static uint64_t get_u64le(const unsigned char *p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; i++) { v |= (uint64_t)p[i] << (8*i); }
    return v;
}

/* ── Nonce derivation ──────────────────────────────────────────────────── */

/*
 * Recipient box nonce: SHA-512("R" || file_nonce || index_le16)[0:24]
 * Domain-separated from chunk nonces to avoid any overlap.
 */
static void derive_box_nonce(unsigned char out[24],
                             const unsigned char fnonce[24], uint16_t idx) {
    unsigned char buf[1 + 24 + 2];
    unsigned char hash[64];
    buf[0] = 'R';
    memcpy(buf + 1, fnonce, 24);
    buf[25] = idx & 0xff;
    buf[26] = (idx >> 8) & 0xff;
    crypto_hash(hash, buf, sizeof buf);
    memcpy(out, hash, 24);
}

/*
 * Chunk nonce: XOR the last 8 bytes of file_nonce with the chunk index.
 * Since file_nonce is random 24 bytes and recipient nonces are hash-derived,
 * no collision is possible between domains.
 */
static void derive_chunk_nonce(unsigned char out[24],
                               const unsigned char fnonce[24], uint64_t idx) {
    memcpy(out, fnonce, 24);
    for (int i = 0; i < 8; i++)
        out[16 + i] ^= (idx >> (8*i)) & 0xff;
}

/* ── read/write helpers ────────────────────────────────────────────────── */

static int read_file(const char *path, unsigned char *buf, size_t len) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    if (fread(buf, 1, len, f) != len) { fclose(f); return -1; }
    fclose(f);
    return 0;
}
static int write_file(const char *path, const unsigned char *buf, size_t len) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return -1; }
    if (fwrite(buf, 1, len, f) != len) { fclose(f); return -1; }
    fclose(f);
    return 0;
}

/* ── keygen ────────────────────────────────────────────────────────────── */

static int cmd_keygen(const char *sk_path, const char *pk_path) {
    unsigned char pk[32], sk[32];
    crypto_box_keypair(pk, sk);
    if (write_file(sk_path, sk, 32) < 0) return 1;
    if (write_file(pk_path, pk, 32) < 0) return 1;
    return 0;
}

/* ── encrypt ───────────────────────────────────────────────────────────── */

static int cmd_encrypt(int nrecip, const char **pk_paths,
                       const char *outpath, const char *inpath) {
    if (nrecip < 1 || nrecip > MAX_RECIP) {
        fprintf(stderr, "Bad recipient count %d\n", nrecip);
        return 1;
    }

    /* Load recipient public keys */
    unsigned char pks[MAX_RECIP][32];
    for (int i = 0; i < nrecip; i++) {
        if (read_file(pk_paths[i], pks[i], 32) < 0) return 1;
    }

    /* Get plaintext length */
    FILE *fin = fopen(inpath, "rb");
    if (!fin) { perror(inpath); return 1; }
    if (fseek(fin, 0, SEEK_END) != 0) { perror("fseek"); fclose(fin); return 1; }
    long flen = ftell(fin);
    if (flen < 0) { perror("ftell"); fclose(fin); return 1; }
    uint64_t pt_len = (uint64_t)flen;
    rewind(fin);

    /* Generate random content key & file nonce */
    unsigned char ckey[32], fnonce[24];
    randombytes(ckey, 32);
    randombytes(fnonce, 24);

    FILE *fout = fopen(outpath, "wb");
    if (!fout) { perror(outpath); fclose(fin); return 1; }

    /* Write header */
    unsigned char hdr[HEADER_SIZE];
    memcpy(hdr, "NV01", 4);
    hdr[4] = 0x01; hdr[5] = 0x00;
    put_u16le(hdr + 6, (uint16_t)nrecip);
    memcpy(hdr + 8, fnonce, 24);
    put_u64le(hdr + 32, pt_len);
    if (fwrite(hdr, 1, HEADER_SIZE, fout) != HEADER_SIZE) goto fail;

    /* Write recipient records */
    for (int i = 0; i < nrecip; i++) {
        unsigned char eph_pk[32], eph_sk[32];
        crypto_box_keypair(eph_pk, eph_sk);

        unsigned char bnonce[24];
        derive_box_nonce(bnonce, fnonce, (uint16_t)i);

        /* crypto_box the 32-byte content key */
        unsigned char m[64], c[64];
        memset(m, 0, 32);               /* ZEROBYTES padding */
        memcpy(m + 32, ckey, 32);       /* payload = content key */
        if (crypto_box(c, m, 64, bnonce, pks[i], eph_sk) != 0) goto fail;

        unsigned char rec[RECIP_SIZE];
        memcpy(rec,      eph_pk, 32);
        memcpy(rec + 32, bnonce, 24);
        memcpy(rec + 56, c + 16, 48);   /* skip BOXZEROBYTES */
        if (fwrite(rec, 1, RECIP_SIZE, fout) != RECIP_SIZE) goto fail;

        memset(eph_sk, 0, 32);          /* wipe ephemeral secret */
    }

    /* Encrypt content in 64 KiB chunks */
    {
        unsigned char *pbuf = malloc(32 + CHUNK_SIZE);   /* ZEROBYTES + chunk */
        unsigned char *cbuf = malloc(32 + CHUNK_SIZE);   /* secretbox output  */
        if (!pbuf || !cbuf) { free(pbuf); free(cbuf); goto fail; }

        uint64_t remaining = pt_len;
        uint64_t ci = 0;
        while (remaining > 0) {
            size_t clen = remaining > CHUNK_SIZE ? CHUNK_SIZE : (size_t)remaining;
            memset(pbuf, 0, 32);
            size_t nr = fread(pbuf + 32, 1, clen, fin);
            if (nr != clen) { free(pbuf); free(cbuf); goto fail; }

            unsigned char cnonce[24];
            derive_chunk_nonce(cnonce, fnonce, ci);
            crypto_secretbox(cbuf, pbuf, 32 + clen, cnonce, ckey);

            /* Write tag(16) + ciphertext(clen) — skip 16 leading zero bytes */
            if (fwrite(cbuf + 16, 1, 16 + clen, fout) != 16 + clen) {
                free(pbuf); free(cbuf); goto fail;
            }
            remaining -= clen;
            ci++;
        }
        free(pbuf);
        free(cbuf);
    }

    fclose(fin);
    fclose(fout);
    memset(ckey, 0, 32);
    return 0;

fail:
    fclose(fin);
    fclose(fout);
    memset(ckey, 0, 32);
    return 1;
}

/* ── decrypt ───────────────────────────────────────────────────────────── */

static int cmd_decrypt(const char *sk_path,
                       const char *outpath, const char *inpath) {
    unsigned char sk[32];
    if (read_file(sk_path, sk, 32) < 0) return 1;

    FILE *fin = fopen(inpath, "rb");
    if (!fin) { perror(inpath); return 1; }

    /* Read header */
    unsigned char hdr[HEADER_SIZE];
    if (fread(hdr, 1, HEADER_SIZE, fin) != HEADER_SIZE) {
        fprintf(stderr, "Truncated header\n"); fclose(fin); return 1;
    }
    if (memcmp(hdr, "NV01", 4) != 0) {
        fprintf(stderr, "Bad magic\n"); fclose(fin); return 1;
    }
    if (hdr[4] != 0x01) {
        fprintf(stderr, "Unsupported version\n"); fclose(fin); return 1;
    }

    uint16_t nrecip = get_u16le(hdr + 6);
    unsigned char fnonce[24];
    memcpy(fnonce, hdr + 8, 24);
    uint64_t pt_len = get_u64le(hdr + 32);

    /* Try each recipient record */
    unsigned char ckey[32];
    int found = 0;

    for (uint16_t i = 0; i < nrecip; i++) {
        unsigned char rec[RECIP_SIZE];
        if (fread(rec, 1, RECIP_SIZE, fin) != RECIP_SIZE) {
            fprintf(stderr, "Truncated recipient record\n"); fclose(fin); return 1;
        }
        if (found) continue;   /* still must read past all records */

        unsigned char eph_pk[32], bnonce[24], enc[48];
        memcpy(eph_pk, rec, 32);
        memcpy(bnonce, rec + 32, 24);
        memcpy(enc, rec + 56, 48);

        /* Reconstruct crypto_box ciphertext with 16 leading zero bytes */
        unsigned char ct[64], pt[64];
        memset(ct, 0, 16);
        memcpy(ct + 16, enc, 48);

        if (crypto_box_open(pt, ct, 64, bnonce, eph_pk, sk) == 0) {
            memcpy(ckey, pt + 32, 32);
            found = 1;
        }
    }

    if (!found) {
        fprintf(stderr, "No matching recipient\n"); fclose(fin); return 1;
    }

    /* Decrypt chunks */
    FILE *fout = fopen(outpath, "wb");
    if (!fout) { perror(outpath); fclose(fin); return 1; }

    unsigned char *ibuf = malloc(16 + CHUNK_SIZE);       /* tag + ciphertext */
    unsigned char *cbuf = malloc(32 + CHUNK_SIZE);       /* prepend 16 zeros */
    unsigned char *pbuf = malloc(32 + CHUNK_SIZE);       /* secretbox_open out */
    if (!ibuf || !cbuf || !pbuf) {
        free(ibuf); free(cbuf); free(pbuf);
        fclose(fin); fclose(fout); return 1;
    }

    uint64_t remaining = pt_len;
    uint64_t ci = 0;
    int err = 0;

    while (remaining > 0 && !err) {
        size_t clen = remaining > CHUNK_SIZE ? CHUNK_SIZE : (size_t)remaining;
        size_t toread = 16 + clen;

        if (fread(ibuf, 1, toread, fin) != toread) {
            fprintf(stderr, "Truncated chunk %lu\n", (unsigned long)ci);
            err = 1; break;
        }

        memset(cbuf, 0, 16);
        memcpy(cbuf + 16, ibuf, 16 + clen);

        unsigned char cnonce[24];
        derive_chunk_nonce(cnonce, fnonce, ci);

        if (crypto_secretbox_open(pbuf, cbuf, 32 + clen, cnonce, ckey) != 0) {
            fprintf(stderr, "Auth failed chunk %lu\n", (unsigned long)ci);
            err = 1; break;
        }

        if (fwrite(pbuf + 32, 1, clen, fout) != clen) {
            err = 1; break;
        }
        remaining -= clen;
        ci++;
    }

    free(ibuf); free(cbuf); free(pbuf);
    fclose(fin); fclose(fout);
    memset(ckey, 0, 32);
    memset(sk, 0, 32);

    if (err) return 1;
    return 0;
}

/* ── CLI ───────────────────────────────────────────────────────────────── */

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage:\n"
        "  %s keygen <sk_file> <pk_file>\n"
        "  %s encrypt -r <pk> [-r <pk> ...] -o <out> <in>\n"
        "  %s decrypt -k <sk> -o <out> <in>\n",
        prog, prog, prog);
}

int main(int argc, char **argv) {
    if (argc < 2) { usage(argv[0]); return 1; }

    if (strcmp(argv[1], "keygen") == 0) {
        if (argc != 4) { usage(argv[0]); return 1; }
        return cmd_keygen(argv[2], argv[3]);
    }

    if (strcmp(argv[1], "encrypt") == 0) {
        const char *pk_files[MAX_RECIP];
        int nrecip = 0;
        const char *outfile = NULL, *infile = NULL;
        int i = 2;
        while (i < argc) {
            if (strcmp(argv[i], "-r") == 0 && i + 1 < argc) {
                if (nrecip >= MAX_RECIP) {
                    fprintf(stderr, "Too many recipients\n"); return 1;
                }
                pk_files[nrecip++] = argv[++i];
            } else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
                outfile = argv[++i];
            } else if (argv[i][0] != '-') {
                infile = argv[i];
            } else {
                fprintf(stderr, "Unknown option: %s\n", argv[i]); return 1;
            }
            i++;
        }
        if (!outfile || !infile || nrecip == 0) {
            fprintf(stderr, "encrypt requires -r, -o, and input file\n");
            return 1;
        }
        return cmd_encrypt(nrecip, pk_files, outfile, infile);
    }

    if (strcmp(argv[1], "decrypt") == 0) {
        const char *sk_file = NULL, *outfile = NULL, *infile = NULL;
        int i = 2;
        while (i < argc) {
            if (strcmp(argv[i], "-k") == 0 && i + 1 < argc) {
                sk_file = argv[++i];
            } else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
                outfile = argv[++i];
            } else if (argv[i][0] != '-') {
                infile = argv[i];
            } else {
                fprintf(stderr, "Unknown option: %s\n", argv[i]); return 1;
            }
            i++;
        }
        if (!sk_file || !outfile || !infile) {
            fprintf(stderr, "decrypt requires -k, -o, and input file\n");
            return 1;
        }
        return cmd_decrypt(sk_file, outfile, infile);
    }

    usage(argv[0]);
    return 1;
}
