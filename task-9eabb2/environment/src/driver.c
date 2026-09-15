#include "mfp.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef MAGMA_ENABLE_CANARIES
extern void __magma_init(const char *output_path);
#endif

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <input_file> [canary_output]\n", argv[0]);
        return 1;
    }

#ifdef MAGMA_ENABLE_CANARIES
    const char *canary_out = (argc >= 3) ? argv[2] : "/tmp/canary_output.csv";
    __magma_init(canary_out);
#endif

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", argv[1]);
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    uint8_t *buf = (uint8_t *)malloc(fsize);
    if (!buf) { fclose(f); return 1; }
    fread(buf, 1, fsize, f);
    fclose(f);

    mfp_document_t doc;
    memset(&doc, 0, sizeof(doc));

    int ret = mfp_parse(buf, fsize, &doc);
    if (ret == 0) {
        char *summary = mfp_render_summary(&doc);
        if (summary) {
            printf("%s", summary);
            free(summary);
        }

        mfp_normalize(&doc);

        uint32_t checksum = mfp_compute_checksum(&doc);
        printf("Checksum: 0x%08x\n", checksum);

        mfp_free(&doc);
    } else {
        fprintf(stderr, "Parse error\n");
    }

    free(buf);
    return (ret == 0) ? 0 : 1;
}
