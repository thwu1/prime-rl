/*
 * mkfs.c - Create an xv6 file system image.
 *
 * Based on the xv6 teaching OS (MIT 6.1810).
 * Compile: gcc -Wall -o mkfs mkfs.c
 * Usage:   ./mkfs <output.img> [files...]
 *
 * Creates a filesystem image with the given files in the root directory.
 * Useful for generating clean reference images for comparison.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

#include "fs.h"

// Filesystem geometry (must match the target image)
#define FSSIZE   1000
#define NINODES  200
#define NLOG     30
#define LOGBLOCKS NLOG

static int fsfd;
static struct superblock sb;
static uint freeinode = 1;
static uint freeblock;

// Contents of the header block, used for both the on-disk header block
// and to keep track in memory of logged block# before commit.
struct logheader {
  int n;
  int block[LOGBLOCKS];
};

static void wsect(uint sec, void *buf)
{
  if (lseek(fsfd, sec * BSIZE, SEEK_SET) != (off_t)(sec * BSIZE)) {
    perror("lseek"); exit(1);
  }
  if (write(fsfd, buf, BSIZE) != BSIZE) {
    perror("write"); exit(1);
  }
}

static void rsect(uint sec, void *buf)
{
  if (lseek(fsfd, sec * BSIZE, SEEK_SET) != (off_t)(sec * BSIZE)) {
    perror("lseek"); exit(1);
  }
  if (read(fsfd, buf, BSIZE) != BSIZE) {
    perror("read"); exit(1);
  }
}

static void winode(uint inum, struct dinode *ip)
{
  char buf[BSIZE];
  uint bn = inum / IPB + sb.inodestart;
  rsect(bn, buf);
  ((struct dinode *)buf)[inum % IPB] = *ip;
  wsect(bn, buf);
}

static void rinode(uint inum, struct dinode *ip)
{
  char buf[BSIZE];
  uint bn = inum / IPB + sb.inodestart;
  rsect(bn, buf);
  *ip = ((struct dinode *)buf)[inum % IPB];
}

static void bitmap_mark(int bno)
{
  char buf[BSIZE];
  uint bmap_block = bno / BPB + sb.bmapstart;
  rsect(bmap_block, buf);
  buf[(bno % BPB) / 8] |= 1 << (bno % 8);
  wsect(bmap_block, buf);
}

static uint do_ialloc(short type)
{
  uint inum = freeinode++;
  struct dinode di;
  memset(&di, 0, sizeof(di));
  di.type = type;
  di.nlink = 1;
  winode(inum, &di);
  return inum;
}

static uint do_balloc(void)
{
  uint b = freeblock++;
  bitmap_mark(b);
  return b;
}

static void iappend(uint inum, void *xp, int n)
{
  char *p = (char *)xp;
  struct dinode din;
  rinode(inum, &din);
  uint off = din.size;

  while (n > 0) {
    uint bnum = off / BSIZE;
    assert(bnum < NDIRECT);  // simplified: no indirect support
    if (din.addrs[bnum] == 0)
      din.addrs[bnum] = do_balloc();
    char buf[BSIZE];
    rsect(din.addrs[bnum], buf);
    uint avail = BSIZE - off % BSIZE;
    uint m = (uint)n < avail ? (uint)n : avail;
    memcpy(buf + off % BSIZE, p, m);
    wsect(din.addrs[bnum], buf);
    n -= m;
    off += m;
    p += m;
  }
  din.size = off;
  winode(inum, &din);
}

int main(int argc, char *argv[])
{
  if (argc < 2) {
    fprintf(stderr, "Usage: mkfs <output.img> [files...]\n");
    return 1;
  }

  uint ninodeblocks = NINODES / IPB + 1;
  uint nbitmap = FSSIZE / BPB + 1;
  uint nmeta = 2 + NLOG + ninodeblocks + nbitmap;

  sb.magic = FSMAGIC;
  sb.size = FSSIZE;
  sb.nblocks = FSSIZE - nmeta;
  sb.ninodes = NINODES;
  sb.nlog = NLOG;
  sb.logstart = 2;
  sb.inodestart = 2 + NLOG;
  sb.bmapstart = 2 + NLOG + ninodeblocks;

  fsfd = open(argv[1], O_RDWR | O_CREAT | O_TRUNC, 0666);
  if (fsfd < 0) { perror(argv[1]); return 1; }

  // Zero the entire image
  char zeroes[BSIZE];
  memset(zeroes, 0, BSIZE);
  for (uint i = 0; i < FSSIZE; i++)
    wsect(i, zeroes);

  // Write superblock at block 1
  char buf[BSIZE];
  memset(buf, 0, BSIZE);
  memcpy(buf, &sb, sizeof(sb));
  wsect(1, buf);

  freeblock = nmeta;

  // Mark all metadata blocks in bitmap
  for (uint i = 0; i < nmeta; i++)
    bitmap_mark(i);

  // Create root directory (inode 1)
  uint rootino = do_ialloc(T_DIR);
  assert(rootino == ROOTINO);

  struct dirent de;
  memset(&de, 0, sizeof(de));
  de.inum = rootino;
  strncpy(de.name, ".", DIRSIZ);
  iappend(rootino, &de, sizeof(de));

  memset(&de, 0, sizeof(de));
  de.inum = rootino;
  strncpy(de.name, "..", DIRSIZ);
  iappend(rootino, &de, sizeof(de));

  // Add files specified on command line
  for (int i = 2; i < argc; i++) {
    const char *path = argv[i];
    const char *slash = strrchr(path, '/');
    const char *name = slash ? slash + 1 : path;

    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); continue; }

    uint ino = do_ialloc(T_FILE);

    memset(&de, 0, sizeof(de));
    de.inum = ino;
    strncpy(de.name, name, DIRSIZ);
    iappend(rootino, &de, sizeof(de));

    char fbuf[BSIZE];
    int cc;
    while ((cc = read(fd, fbuf, sizeof(fbuf))) > 0)
      iappend(ino, fbuf, cc);
    close(fd);

    printf("added: %s (inode %d)\n", name, ino);
  }

  // Update root nlink
  struct dinode din;
  rinode(rootino, &din);
  din.nlink = 1;
  winode(rootino, &din);

  close(fsfd);
  printf("mkfs: %d blocks (%d meta, %d data), %d inodes, %d log\n",
         FSSIZE, (int)nmeta, (int)(FSSIZE - nmeta), NINODES, NLOG);
  return 0;
}
