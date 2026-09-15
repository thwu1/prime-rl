#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ndp.h"

/*
 * BULK payload: block-oriented data transfer.
 * See ndp.h for the full block format specification.
 */

int handle_bulk(const uint8_t *payload, size_t len, uint8_t flags) {
    if (len < 4) {
        fprintf(stderr, "BULK: payload too short\n");
        return -1;
    }

    uint16_t num_blocks = read_u16_be(payload);
    /* uint16_t reserved = read_u16_be(payload + 2); */

    if (num_blocks == 0) {
        fprintf(stderr, "BULK: no blocks\n");
        return -1;
    }

    uint8_t *output = NULL;
    size_t output_size = 0;
    size_t output_capacity = 0;
    size_t offset = 4;
    int status = 0;

    for (uint16_t i = 0; i < num_blocks; i++) {
        if (offset + 4 > len) {
            fprintf(stderr, "BULK: block %u header extends past payload\n", i);
            status = -1;
            break;
        }

        uint16_t block_type = read_u16_be(payload + offset);
        uint16_t block_len = read_u16_be(payload + offset + 2);
        offset += 4;

        if (offset + block_len > len) {
            fprintf(stderr, "BULK: block %u data extends past payload\n", i);
            status = -1;
            break;
        }

        const uint8_t *block_data = payload + offset;

        switch (block_type) {
            case BULK_APPEND: {
                /* Grow output buffer and append incoming data */
                size_t new_size = output_size + block_len;
                if (new_size > 65536) {
                    fprintf(stderr, "BULK: output exceeds maximum size\n");
                    status = -1;
                    goto cleanup;
                }
                if (new_size > output_capacity) {
                    size_t new_cap = output_capacity ? output_capacity * 2 : 256;
                    while (new_cap < new_size)
                        new_cap *= 2;
                    uint8_t *tmp = realloc(output, new_cap);
                    if (!tmp) {
                        fprintf(stderr, "BULK: allocation failed\n");
                        status = -1;
                        goto cleanup;
                    }
                    output = tmp;
                    output_capacity = new_cap;
                }
                memcpy(output + output_size, block_data, block_len);
                output_size += block_len;
                break;
            }

            case BULK_OVERWRITE: {
                /* Overwrite data at a specified offset in the output buffer */
                if (block_len < 4) {
                    fprintf(stderr, "BULK: overwrite block too short\n");
                    break;
                }
                uint32_t write_offset = read_u32_be(block_data);
                size_t write_len = block_len - 4;

                if (output == NULL) {
                    fprintf(stderr, "BULK: overwrite before any append\n");
                    break;
                }

                /* Copy data to output at the specified offset */
                memcpy(output + write_offset, block_data + 4, write_len);
                break;
            }

            case BULK_FINALIZE: {
                /* Verify output size matches expected value */
                if (block_len >= 4) {
                    uint32_t expected = read_u32_be(block_data);
                    if (output_size != (size_t)expected) {
                        fprintf(stderr, "BULK: size mismatch: got %zu expected %u\n",
                                output_size, expected);
                    }
                }
                if (flags & NDP_FLAG_VERBOSE) {
                    printf("BULK: finalized, output_size=%zu\n", output_size);
                }
                printf("BULK: complete (%zu bytes)\n", output_size);
                goto cleanup;
            }

            default:
                if (flags & NDP_FLAG_VERBOSE) {
                    fprintf(stderr, "BULK: unknown block type 0x%04X\n", block_type);
                }
                break;
        }

        offset += block_len;
    }

cleanup:
    free(output);
    return status;
}
