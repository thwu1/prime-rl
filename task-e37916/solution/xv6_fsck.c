/*
 * xv6 Filesystem Consistency Checker
 * Parses a raw xv6 filesystem image and detects structural inconsistencies.
 * Usage: xv6-fsck <image_path>
 * Output: JSON report to stdout
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* xv6 filesystem constants */
#define BSIZE 1024
#define NDIRECT 12
#define NINDIRECT 256
#define IPB 16
#define BPB 8192
#define FSMAGIC 0x10203040
#define T_DIR 1
#define DIRSIZ 14

static uint8_t *disk;
static size_t disk_len;

static uint32_t sb_magic, sb_size, sb_nblocks, sb_ninodes;
static uint32_t sb_nlog, sb_logstart, sb_inodestart, sb_bmapstart;
static uint32_t datastart;

/* Block reference tracking: (block, inum) pairs */
struct bref {
    uint32_t block;
    uint32_t inum;
};

static struct bref *refs;
static int nrefs, rcap;

/* Directory reference counts per inode */
static int *dref;

/* JSON output state */
static int first_err;

static void addref(uint32_t block, uint32_t inum)
{
    if (nrefs >= rcap) {
        rcap = rcap ? rcap * 2 : 4096;
        refs = realloc(refs, (size_t)rcap * sizeof(*refs));
        if (!refs) { perror("realloc"); exit(1); }
    }
    refs[nrefs].block = block;
    refs[nrefs].inum = inum;
    nrefs++;
}

static void read_superblock(void)
{
    if (disk_len < 2 * BSIZE) {
        fprintf(stderr, "Image too small for superblock\n");
        exit(1);
    }
    memcpy(&sb_magic, disk + BSIZE, 4);
    memcpy(&sb_size, disk + BSIZE + 4, 4);
    memcpy(&sb_nblocks, disk + BSIZE + 8, 4);
    memcpy(&sb_ninodes, disk + BSIZE + 12, 4);
    memcpy(&sb_nlog, disk + BSIZE + 16, 4);
    memcpy(&sb_logstart, disk + BSIZE + 20, 4);
    memcpy(&sb_inodestart, disk + BSIZE + 24, 4);
    memcpy(&sb_bmapstart, disk + BSIZE + 28, 4);
}

static int get_inode_type(uint32_t inum)
{
    size_t pos = ((size_t)(inum / IPB + sb_inodestart)) * BSIZE + (inum % IPB) * 64;
    if (pos + 64 > disk_len) return 0;
    int16_t type;
    memcpy(&type, disk + pos, 2);
    return type;
}

static int16_t get_inode_nlink(uint32_t inum)
{
    size_t pos = ((size_t)(inum / IPB + sb_inodestart)) * BSIZE + (inum % IPB) * 64;
    if (pos + 64 > disk_len) return 0;
    int16_t nlink;
    memcpy(&nlink, disk + pos + 6, 2);
    return nlink;
}

static void get_inode_addrs(uint32_t inum, uint32_t addrs[NDIRECT + 1])
{
    size_t pos = ((size_t)(inum / IPB + sb_inodestart)) * BSIZE + (inum % IPB) * 64;
    memcpy(addrs, disk + pos + 12, (NDIRECT + 1) * 4);
}

static uint32_t get_inode_size(uint32_t inum)
{
    size_t pos = ((size_t)(inum / IPB + sb_inodestart)) * BSIZE + (inum % IPB) * 64;
    uint32_t sz;
    memcpy(&sz, disk + pos + 8, 4);
    return sz;
}

static int get_bitmap(uint32_t b)
{
    size_t off = ((size_t)(sb_bmapstart + b / BPB)) * BSIZE + (b % BPB) / 8;
    if (off >= disk_len) return 0;
    return (disk[off] >> ((b % BPB) % 8)) & 1;
}

static void collect_blocks(uint32_t inum)
{
    if (get_inode_type(inum) == 0) return;

    uint32_t addrs[NDIRECT + 1];
    get_inode_addrs(inum, addrs);

    /* Direct blocks */
    for (int i = 0; i < NDIRECT; i++) {
        if (addrs[i] != 0)
            addref(addrs[i], inum);
    }

    /* Indirect block */
    uint32_t ind = addrs[NDIRECT];
    if (ind != 0) {
        addref(ind, inum);
        if (ind < sb_size && (size_t)ind * BSIZE + BSIZE <= disk_len) {
            uint32_t ents[NINDIRECT];
            memcpy(ents, disk + (size_t)ind * BSIZE, sizeof(ents));
            for (int j = 0; j < NINDIRECT; j++) {
                if (ents[j] != 0)
                    addref(ents[j], inum);
            }
        }
    }
}

static void walk_directory(uint32_t inum)
{
    if (get_inode_type(inum) != T_DIR) return;

    uint32_t sz = get_inode_size(inum);
    uint32_t addrs[NDIRECT + 1];
    get_inode_addrs(inum, addrs);

    uint32_t off = 0;
    while (off < sz) {
        uint32_t bi = off / BSIZE;
        uint32_t boff = off % BSIZE;
        uint32_t ba;

        if (bi < NDIRECT) {
            ba = addrs[bi];
        } else {
            uint32_t ind = addrs[NDIRECT];
            if (ind == 0 || ind >= sb_size) { off += 16; continue; }
            uint32_t inner = bi - NDIRECT;
            if (inner >= NINDIRECT) break;
            memcpy(&ba, disk + (size_t)ind * BSIZE + inner * 4, 4);
        }

        if (ba == 0 || ba >= sb_size) { off += 16; continue; }
        size_t pos = (size_t)ba * BSIZE + boff;
        if (pos + 16 > disk_len) break;

        uint16_t dinum;
        memcpy(&dinum, disk + pos, 2);

        if (dinum != 0 && dinum < sb_ninodes) {
            char nm[DIRSIZ + 1];
            memcpy(nm, disk + pos + 2, DIRSIZ);
            nm[DIRSIZ] = '\0';
            if (strcmp(nm, ".") != 0) {
                dref[dinum]++;
            }
        }
        off += 16;
    }
}

static int cmpref(const void *a, const void *b)
{
    const struct bref *ra = (const struct bref *)a;
    const struct bref *rb = (const struct bref *)b;
    if (ra->block != rb->block)
        return ra->block < rb->block ? -1 : 1;
    if (ra->inum != rb->inum)
        return ra->inum < rb->inum ? -1 : 1;
    return 0;
}

static void emit_sep(void)
{
    if (!first_err) printf(",");
    first_err = 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <image>\n", argv[0]);
        return 1;
    }

    /* Read image into memory */
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END);
    disk_len = (size_t)ftell(f);
    rewind(f);
    disk = malloc(disk_len);
    if (!disk) { perror("malloc"); return 1; }
    if (fread(disk, 1, disk_len, f) != disk_len) { perror("fread"); return 1; }
    fclose(f);

    /* Parse superblock */
    read_superblock();
    if (sb_magic != FSMAGIC) {
        printf("{\"errors\":[{\"type\":\"BAD_MAGIC\"}]}\n");
        free(disk);
        return 0;
    }

    uint32_t nbmap = (sb_size + BPB - 1) / BPB;
    datastart = sb_bmapstart + nbmap;

    dref = calloc(sb_ninodes, sizeof(int));
    if (!dref) { perror("calloc"); return 1; }

    /* Pass 1: collect all block references from all inodes */
    for (uint32_t i = 0; i < sb_ninodes; i++)
        collect_blocks(i);

    /* Sort references by (block, inum) for group processing */
    if (nrefs > 0)
        qsort(refs, (size_t)nrefs, sizeof(*refs), cmpref);

    /* Bitmap for tracking which valid data blocks are referenced */
    size_t rmap_bytes = (sb_size + 7) / 8;
    uint8_t *rmap = calloc(rmap_bytes, 1);
    if (!rmap) { perror("calloc"); return 1; }

    first_err = 1;
    printf("{\"errors\":[");

    /* Process sorted block refs: detect invalid, duplicate, bitmap-free */
    int r = 0;
    while (r < nrefs) {
        uint32_t b = refs[r].block;

        /* Collect unique inodes referencing this block */
        uint32_t uniq[512];
        int nu = 0;
        while (r < nrefs && refs[r].block == b) {
            if (nu == 0 || uniq[nu - 1] != refs[r].inum) {
                if (nu < 512)
                    uniq[nu++] = refs[r].inum;
            }
            r++;
        }

        if (b >= sb_size || b < datastart) {
            /* Invalid block reference */
            for (int j = 0; j < nu; j++) {
                emit_sep();
                printf("{\"type\":\"INVALID_BLOCK_REF\",\"inode\":%u,\"block\":%u}",
                       uniq[j], b);
            }
        } else {
            /* Mark block as referenced */
            rmap[b / 8] |= (uint8_t)(1 << (b % 8));

            /* Duplicate block reference */
            if (nu > 1) {
                emit_sep();
                printf("{\"type\":\"DUPLICATE_BLOCK_REF\",\"block\":%u,\"inodes\":[", b);
                for (int j = 0; j < nu; j++) {
                    if (j > 0) printf(",");
                    printf("%u", uniq[j]);
                }
                printf("]}");
            }

            /* Bitmap marked free but block is referenced */
            if (!get_bitmap(b)) {
                emit_sep();
                printf("{\"type\":\"BITMAP_MARKED_FREE\",\"block\":%u,\"inodes\":[", b);
                for (int j = 0; j < nu; j++) {
                    if (j > 0) printf(",");
                    printf("%u", uniq[j]);
                }
                printf("]}");
            }
        }
    }

    /* Bitmap marked used: data blocks with bitmap set but not referenced */
    for (uint32_t b = datastart; b < sb_size; b++) {
        int bm = get_bitmap(b);
        int ref = (rmap[b / 8] >> (b % 8)) & 1;
        if (bm && !ref) {
            emit_sep();
            printf("{\"type\":\"BITMAP_MARKED_USED\",\"block\":%u}", b);
        }
    }

    /* Pass 2: walk all directories to count nlink references */
    for (uint32_t i = 0; i < sb_ninodes; i++)
        walk_directory(i);

    /* Orphan inodes: allocated but no directory entry pointing to them */
    for (uint32_t i = 1; i < sb_ninodes; i++) {
        if (get_inode_type(i) != 0 && dref[i] == 0) {
            emit_sep();
            printf("{\"type\":\"ORPHAN_INODE\",\"inode\":%u}", i);
        }
    }

    /* nlink mismatches */
    for (uint32_t i = 1; i < sb_ninodes; i++) {
        if (get_inode_type(i) == 0) continue;
        int16_t actual_nlink = get_inode_nlink(i);
        if (dref[i] != (int)actual_nlink) {
            emit_sep();
            printf("{\"type\":\"INODE_NLINK_MISMATCH\",\"inode\":%u,\"expected\":%d,\"actual\":%d}",
                   i, dref[i], (int)actual_nlink);
        }
    }

    printf("]}\n");

    free(disk);
    free(dref);
    free(refs);
    free(rmap);
    return 0;
}
