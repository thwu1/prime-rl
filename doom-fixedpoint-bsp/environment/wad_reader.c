/*
 * WAD file parser implementation.
 * Handles header parsing, directory reading, and lump extraction.
 * Converts on-disk map structures to runtime fixed-point representation.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "wad_reader.h"

static FILE       *wad_fp    = NULL;
static wadinfo_t   wad_hdr;
static filelump_t *wad_dir   = NULL;
static int         wad_nlumps = 0;

/* Linear search for a named lump in the directory */
static int find_lump(const char *name, int32_t *off, int32_t *sz)
{
    for (int i = 0; i < wad_nlumps; i++) {
        if (strncasecmp(wad_dir[i].name, name, 8) == 0) {
            *off = wad_dir[i].filepos;
            *sz  = wad_dir[i].size;
            return 0;
        }
    }
    return -1;
}

int wad_open(const char *filename)
{
    wad_fp = fopen(filename, "rb");
    if (!wad_fp) return -1;

    /* Read 4-byte identification */
    if (fread(wad_hdr.identification, 1, 4, wad_fp) != 4)
        goto fail;

    /* Read numlumps (4 bytes, little-endian on disk) */
    if (fread(&wad_hdr.numlumps, 4, 1, wad_fp) != 1)
        goto fail;
    /* Byte-swap: WAD files originate on big-endian 68k Nextstations */
    wad_hdr.numlumps = ((wad_hdr.numlumps >> 24) & 0xFF)       |
                       ((wad_hdr.numlumps >>  8) & 0xFF00)     |
                       ((wad_hdr.numlumps <<  8) & 0xFF0000)   |
                       ((wad_hdr.numlumps << 24) & 0xFF000000u);

    /* Read infotableofs */
    if (fread(&wad_hdr.infotableofs, 4, 1, wad_fp) != 1)
        goto fail;

    /* Validate identification */
    if (strncmp(wad_hdr.identification, "IWAD", 4) != 0 &&
        strncmp(wad_hdr.identification, "PWAD", 4) != 0) {
        fprintf(stderr, "Error: not a valid WAD file\n");
        goto fail;
    }

    if (wad_hdr.numlumps <= 0 || wad_hdr.numlumps > 65536) {
        fprintf(stderr, "Error: WAD lump count out of range (%d)\n",
                wad_hdr.numlumps);
        goto fail;
    }

    wad_nlumps = wad_hdr.numlumps;
    wad_dir = calloc(wad_nlumps, sizeof(filelump_t));
    if (!wad_dir) goto fail;

    /* Seek to directory and read entries */
    fseek(wad_fp, wad_hdr.infotableofs, SEEK_SET);
    for (int i = 0; i < wad_nlumps - 1; i++) {
        if (fread(&wad_dir[i].filepos, 4, 1, wad_fp) != 1) goto fail;
        if (fread(&wad_dir[i].size,    4, 1, wad_fp) != 1) goto fail;
        if (fread( wad_dir[i].name,  1, 8, wad_fp)   != 8) goto fail;
    }

    return 0;

fail:
    if (wad_fp) { fclose(wad_fp); wad_fp = NULL; }
    free(wad_dir); wad_dir = NULL;
    wad_nlumps = 0;
    return -1;
}

int wad_load_nodes(node_t **nodes_out, int *count_out)
{
    int32_t off, sz;
    if (find_lump("NODES", &off, &sz) != 0) return -1;

    int n = sz / (int)sizeof(mapnode_t);
    if (n <= 0) return -1;

    mapnode_t *raw = malloc(sz);
    if (!raw) return -1;

    fseek(wad_fp, off, SEEK_SET);
    if ((int)fread(raw, sizeof(mapnode_t), n, wad_fp) != n) {
        free(raw);
        return -1;
    }

    node_t *nodes = calloc(n, sizeof(node_t));
    if (!nodes) { free(raw); return -1; }

    for (int i = 0; i < n; i++) {
        /* Convert int16 map coordinates to 16.16 fixed-point */
        nodes[i].x  = (fixed_t)raw[i].x  << (FRACBITS - 1);
        nodes[i].y  = (fixed_t)raw[i].y  << (FRACBITS - 1);
        nodes[i].dx = (fixed_t)raw[i].dx << (FRACBITS - 1);
        nodes[i].dy = (fixed_t)raw[i].dy << (FRACBITS - 1);
        for (int c = 0; c < 2; c++)
            for (int b = 0; b < 4; b++)
                nodes[i].bbox[c][b] =
                    (fixed_t)raw[i].bbox[c][b] << (FRACBITS - 1);
        nodes[i].children[0] = raw[i].children[0];
        nodes[i].children[1] = raw[i].children[1];
    }

    free(raw);
    *nodes_out  = nodes;
    *count_out  = n;
    return 0;
}

int wad_load_subsectors(subsector_t **ss_out, int *count_out)
{
    int32_t off, sz;
    if (find_lump("SSECTORS", &off, &sz) != 0)
        return -1;

    int n = sz / (int)sizeof(mapsubsector_t);
    if (n <= 0) return -1;

    mapsubsector_t *raw = malloc(sz);
    if (!raw) return -1;

    fseek(wad_fp, off, SEEK_SET);
    if ((int)fread(raw, sizeof(mapsubsector_t), n, wad_fp) != n) {
        free(raw);
        return -1;
    }

    subsector_t *ss = calloc(n, sizeof(subsector_t));
    if (!ss) { free(raw); return -1; }

    for (int i = 0; i < n; i++) {
        ss[i].numsegs  = raw[i].numsegs;
        ss[i].firstseg = raw[i].firstseg;
    }

    free(raw);
    *ss_out    = ss;
    *count_out = n;
    return 0;
}

void wad_close(void)
{
    if (wad_fp) { fclose(wad_fp); wad_fp = NULL; }
    free(wad_dir);
    wad_dir    = NULL;
    wad_nlumps = 0;
}

unsigned int W_LumpNameHash(const char *s)
{
    unsigned int hash = 5381;
    for (int i = 0; i < 8 && s[i] != '\0'; i++) {
        hash = ((hash << 4) ^ hash) ^
               (unsigned char)toupper((unsigned char)s[i]);
    }
    return hash;
}

uint32_t wad_directory_hash(void)
{
    /* Not yet implemented — computes FNV-1a over directory entries */
    return 0;
}
