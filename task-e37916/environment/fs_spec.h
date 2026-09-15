/*
 * xv6 On-Disk Filesystem Format Specification
 * This header can be directly #included in C implementations.
 *
 * All multi-byte values are stored little-endian (RISC-V / x86 native byte order).
 */

#ifndef XV6_FS_SPEC_H
#define XV6_FS_SPEC_H

#include <stdint.h>

/* Block size in bytes */
#define BSIZE 1024

/* Root inode number (inode 0 is always unused) */
#define ROOTINO 1

/* File types stored in dinode.type */
#define T_DIR    1   /* Directory */
#define T_FILE   2   /* Regular file */
#define T_DEVICE 3   /* Device file */

/* Filesystem magic number for validation */
#define FSMAGIC 0x10203040

/* Number of direct block pointers per inode */
#define NDIRECT 12

/* Number of entries in one indirect block */
#define NINDIRECT 256   /* BSIZE / sizeof(uint32_t) = 1024 / 4 */

/* Maximum file size in blocks */
#define MAXFILE 268     /* NDIRECT + NINDIRECT = 12 + 256 */

/*
 * On-disk layout (block numbers):
 *
 *   Block 0          : boot block (unused by filesystem)
 *   Block 1          : superblock (struct superblock, 32 bytes at offset 0)
 *   Blocks [logstart, logstart+nlog)       : log blocks
 *   Blocks [inodestart, inodestart+niblocks) : inode blocks
 *   Blocks [bmapstart, bmapstart+nbmapblocks) : free block bitmap
 *   Blocks [datastart, size)               : data blocks
 *
 * where:
 *   logstart   = 2
 *   inodestart = logstart + nlog
 *   niblocks   = ceil(ninodes / IPB)
 *   bmapstart  = inodestart + niblocks
 *   nbmapblocks = ceil(size / BPB)
 *   datastart  = bmapstart + nbmapblocks
 */

/*
 * Superblock structure (32 bytes total)
 * Located at byte offset BSIZE (= 1024) in the image file, i.e., block 1.
 */
struct superblock {
    uint32_t magic;       /* Must be FSMAGIC (0x10203040) */
    uint32_t size;        /* Total filesystem size in blocks */
    uint32_t nblocks;     /* Number of data blocks */
    uint32_t ninodes;     /* Total number of inodes */
    uint32_t nlog;        /* Number of log blocks */
    uint32_t logstart;    /* Block number of first log block */
    uint32_t inodestart;  /* Block number of first inode block */
    uint32_t bmapstart;   /* Block number of first free-map block */
};

/*
 * On-disk inode structure (64 bytes total)
 *
 * IPB (Inodes Per Block) = BSIZE / sizeof(struct dinode) = 1024 / 64 = 16
 *
 * Inode number `i` is located at:
 *   block = i / IPB + sb.inodestart
 *   byte offset within block = (i % IPB) * 64
 *   absolute byte offset in image = block * BSIZE + (i % IPB) * 64
 */
struct dinode {
    int16_t  type;              /* 0=free, T_DIR=1, T_FILE=2, T_DEVICE=3 */
    int16_t  major;             /* Major device number (T_DEVICE only) */
    int16_t  minor;             /* Minor device number (T_DEVICE only) */
    int16_t  nlink;             /* Number of directory entries referring to this inode */
    uint32_t size;              /* File size in bytes */
    uint32_t addrs[NDIRECT+1];  /* Block addresses:
                                 *   addrs[0..11]  = direct block numbers
                                 *   addrs[12]     = indirect block number
                                 * A value of 0 means "not allocated".
                                 * The indirect block contains NINDIRECT (256)
                                 * uint32 entries, each a data block number (0 = not allocated).
                                 */
};

/* Inodes per block */
#define IPB  16   /* BSIZE / sizeof(struct dinode) = 1024 / 64 */

/* Block containing inode i */
#define IBLOCK(i, sb)  ((i) / IPB + (sb).inodestart)

/* Bitmap bits per block */
#define BPB  8192   /* BSIZE * 8 = 1024 * 8 */

/* Bitmap block containing the bit for block b */
#define BBLOCK(b, sb)  ((b) / BPB + (sb).bmapstart)

/*
 * Within a bitmap block, block b's bit is at:
 *   byte index = (b % BPB) / 8
 *   bit index  = (b % BPB) % 8
 * Bit value 1 = block allocated, 0 = block free.
 */

/* Maximum filename length in a directory entry */
#define DIRSIZ 14

/*
 * Directory entry structure (16 bytes total)
 *
 * A directory inode's data is a sequence of these structures.
 * An entry with inum == 0 is a free (deleted or unused) slot.
 * The name field may fill all DIRSIZ bytes without a NUL terminator.
 */
struct xv6_dirent {
    uint16_t inum;          /* Inode number (0 = free entry) */
    char     name[DIRSIZ];  /* Filename, up to 14 bytes, may lack NUL */
};

/*
 * nlink semantics in xv6:
 *
 * When a directory is created under parent P:
 *   - The new dir D gets nlink = 1 (from P's directory entry for D)
 *   - P's nlink is incremented by 1 (from D's ".." entry pointing to P)
 *   - D's "." entry does NOT contribute to nlink (explicitly excluded)
 *
 * Therefore:
 *   - A file's nlink = number of hard links (directory entries) to it
 *   - A directory's nlink = 1 (parent's entry) + number of child directories
 *   - Root directory: nlink = 1 (own "..") + number of subdirectories
 *
 * In general: nlink = count of ALL directory entries pointing to the inode,
 * EXCLUDING "." entries, INCLUDING ".." entries.
 */

#endif /* XV6_FS_SPEC_H */
