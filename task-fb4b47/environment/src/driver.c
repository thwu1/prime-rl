#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "imgutil.h"

#ifdef MAGMA_ENABLE_CANARIES
extern void magma_init(void);
#endif

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <bug_number>\n", argv[0]);
        return 1;
    }

#ifdef MAGMA_ENABLE_CANARIES
    magma_init();
#endif

    int bug = atoi(argv[1]);

    if (bug == 1) {
        /* Exercise BUG001: integer overflow
         * 65536 * 65537 * 1 = 4295032832, overflows 32-bit unsigned to 65536 */
        int r = img_validate_dimensions(65536, 65537, 1);
        printf("BUG001: validate_dimensions(65536,65537,1) = %d\n", r);
    }

    if (bug == 2) {
        /* Exercise BUG002: palette OOB read
         * Pixel value 200 exceeds palette_entries=128 */
        unsigned char pixels[] = {10, 200, 50};
        unsigned char palette[256];
        memset(palette, 0xAA, sizeof(palette));
        img_apply_palette(pixels, 3, palette, 128);
        printf("BUG002: apply_palette(pixels=[10,200,50], palette_size=128)\n");
    }

    if (bug == 3) {
        /* Exercise BUG003: off-by-one
         * length=8, loop goes to i=8 (OOB) */
        unsigned char scanline[16] = {1,2,3,4,5,6,7,8,0,0,0,0,0,0,0,0};
        img_filter_scanline(scanline, 8, 1);
        printf("BUG003: filter_scanline(length=8, filter=1)\n");
    }

    if (bug == 4) {
        /* Exercise BUG004: buffer overflow in metadata copy
         * 40-byte input into 16-byte output buffer */
        const char *data = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        char output[64];
        memset(output, 0, sizeof(output));
        int r = img_parse_metadata(data, 40, output, 16);
        printf("BUG004: parse_metadata(40 bytes into 16-byte buf) wrote %d\n", r);
    }

    if (bug == 5) {
        /* Exercise BUG005: signed integer confusion
         * First byte 0x80 makes stated_len negative */
        unsigned char chunk[] = {0x80, 0x00, 0x00, 0x01, 0xAA, 0xBB, 0xCC, 0xDD};
        int r = img_validate_chunk(chunk, 8);
        printf("BUG005: validate_chunk(high-bit set) = %d\n", r);
    }

    return 0;
}
