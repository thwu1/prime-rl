/*
 * WAD file parser for Doom-format WAD files.
 * Reads header, directory, and extracts NODES / SSECTORS lumps.
 */


#ifndef WAD_READER_H
#define WAD_READER_H

#include <stdint.h>
#include "fixed_math.h"

/* WAD file header (12 bytes) */
typedef struct {
    char     identification[4];  /* "IWAD" or "PWAD" */
    int32_t  numlumps;
    int32_t  infotableofs;
} wadinfo_t;

/* WAD directory entry (16 bytes) */
typedef struct {
    int32_t  filepos;
    int32_t  size;
    char     name[8];
} filelump_t;

/* On-disk BSP node (28 bytes, all little-endian) */
typedef struct __attribute__((packed)) {
    int16_t   x, y, dx, dy;
    int16_t   bbox[2][4];
    uint16_t  children[2];
} mapnode_t;

/* On-disk subsector (4 bytes) */
typedef struct __attribute__((packed)) {
    uint16_t  numsegs;
    uint16_t  firstseg;
} mapsubsector_t;

/* Runtime BSP node with fixed_t coordinates */
typedef struct {
    fixed_t   x, y, dx, dy;
    fixed_t   bbox[2][4];
    uint16_t  children[2];
} node_t;

/* Runtime subsector */
typedef struct {
    uint16_t  numsegs;
    uint16_t  firstseg;
} subsector_t;

/* Flag indicating a child reference is a subsector leaf */
#define NF_SUBSECTOR  0x8000

int  wad_open(const char *filename);
int  wad_load_nodes(node_t **nodes_out, int *count_out);
int  wad_load_subsectors(subsector_t **ss_out, int *count_out);
void wad_close(void);

unsigned int W_LumpNameHash(const char *s);
uint32_t     wad_directory_hash(void);

#endif /* WAD_READER_H */
