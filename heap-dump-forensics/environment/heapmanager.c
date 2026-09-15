/* heapmanager.c - Classified Data Storage System
 *
 * This program stores encrypted classified data on the heap.
 * The encryption key is derived from the heap layout itself,
 * making the data unrecoverable without access to process memory.
 *
 * Build: gcc -O0 -o heapmanager heapmanager.c -lcrypto
 *
 * HEAP DUMP CAPTURE NOTES:
 *   - ASLR was disabled: echo 0 > /proc/sys/kernel/randomize_va_space
 *   - Heap base address: 0x55555555a000
 *   - Dump size: 0x600 bytes from heap base
 *   - Captured via GDB: dump binary memory heap_dump.bin 0x55555555a000 0x55555555a600
 *   - glibc version: 2.39 (Ubuntu 24.04, x86-64)
 *
 */

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <openssl/sha.h>

/*
 * HEAP LAYOUT OVERVIEW (glibc 2.39, x86-64)
 * ==========================================
 *
 * glibc chunk header (16 bytes on x64):
 *   offset 0x00: prev_size (8 bytes) - size of previous chunk if it was freed
 *   offset 0x08: size      (8 bytes) - size of this chunk including header
 *     Low 3 bits are flags:
 *       bit 0 (0x1): PREV_INUSE  - previous chunk is allocated
 *       bit 1 (0x2): IS_MMAPPED  - chunk obtained via mmap
 *       bit 2 (0x4): NON_MAIN_ARENA
 *     Actual chunk size = size & ~0x7
 *     Usable data size  = chunk_size - 0x10 (subtract header)
 *
 * malloc(N) -> chunk_size = ((N + 0x8 + 0xF) & ~0xF)
 *   e.g., malloc(0x40) -> chunk_size = 0x50, usable = 0x40
 *         malloc(0x60) -> chunk_size = 0x70, usable = 0x60
 *
 * TCACHE (Thread Cache, glibc >= 2.26):
 *   - First heap chunk is always tcache_perthread_struct (size 0x290)
 *   - Structure: { uint16_t counts[64]; tcache_entry *entries[64]; }
 *   - counts offset from user data start: 0 (128 bytes)
 *   - entries offset from user data start: 128 (0x80) = 512 bytes
 *   - Bin index = (chunk_size - 0x20) / 0x10
 *     e.g., chunk_size 0x30 -> idx 1, chunk_size 0x50 -> idx 3
 *   - Max 7 chunks per bin
 *   - LIFO: last freed = head of list
 *
 * SAFE-LINKING (glibc >= 2.34):
 *   When a chunk is freed to tcache, its 'next' pointer is mangled:
 *     stored_value = PROTECT_PTR(pos, ptr)
 *   where:
 *     pos = address of the fd/next field in the freed chunk
 *     ptr = actual pointer to next freed chunk (or NULL)
 *     PROTECT_PTR(pos, ptr) = (pos >> 12) ^ ptr
 *   To recover the actual pointer:
 *     ptr = (pos >> 12) ^ stored_value
 *
 *   Additionally, a 'key' field at offset +8 in the freed chunk
 *   stores the address of the tcache_perthread_struct (user data),
 *   used for double-free detection.
 */

#define NUM_CHUNKS 9

static void *chunks[NUM_CHUNKS];
static size_t chunk_sizes[] = {0x80, 0x20, 0x40, 0x60, 0x40, 0xA0, 0x30, 0x20, 0x50};

/*
 * KEY DERIVATION
 * ==============
 * The encryption key is derived from 5 parameters extracted from the
 * live heap state. All values are serialized as 8-byte little-endian
 * uint64_t and concatenated (40 bytes total), then hashed with SHA-256
 * to produce the 32-byte encryption key.
 *
 * Parameters:
 *   P1: Virtual address of chunk[3]'s user data region
 *       (the pointer returned by malloc for the 4th user allocation,
 *        NOT counting the tcache_perthread_struct)
 *
 *   P2: The raw size field from chunk[5]'s malloc_chunk header
 *       (includes the PREV_INUSE flag bit; read directly from
 *        the 8 bytes at chunk[5]_userdata - 8)
 *
 *   P3: The de-mangled 'next' (fd) pointer from the HEAD entry
 *       of the tcache bin for chunk size 0x50 (bin index 3).
 *       The head entry is the most recently freed chunk of that size.
 *       Apply PROTECT_PTR reversal to recover the actual pointer value.
 *
 *   P4: First 8 bytes of chunk[1]'s user data, read as uint64_t LE
 *
 *   P5: First 8 bytes of chunk[6]'s user data, read as uint64_t LE
 *
 * key = SHA-256( P1 || P2 || P3 || P4 || P5 )
 */

void derive_key(unsigned char *key_out) {
    uint64_t params[5];

    /* P1: address of chunk[3] user data */
    params[0] = (uint64_t)chunks[3];

    /* P2: raw size field of chunk[5]
     * The size field is at (chunk_userdata - 8) */
    params[1] = *(uint64_t *)((char *)chunks[5] - 8);

    /* P3: de-mangled fd of the tcache head for size-0x50 bin
     * Chunk[4] was the last freed chunk of size 0x50, so it is the head.
     * Its fd field (at chunks[4]+0) contains the mangled next pointer.
     * De-mangle: actual = (pos >> 12) ^ mangled
     * where pos = address of the fd field = chunks[4] */
    {
        uint64_t mangled_fd = *(uint64_t *)chunks[4];
        uint64_t pos = (uint64_t)chunks[4];
        params[2] = (pos >> 12) ^ mangled_fd;
    }

    /* P4: first qword of chunk[1] data */
    params[3] = *(uint64_t *)chunks[1];

    /* P5: first qword of chunk[6] data */
    params[4] = *(uint64_t *)chunks[6];

    SHA256((unsigned char *)params, sizeof(params), key_out);
}

/*
 * ENCRYPTION
 * ==========
 * Simple XOR cipher with the 32-byte key repeated cyclically.
 * Applied to chunks[3], chunks[5], and chunks[8].
 * Each chunk's data region is encrypted independently starting
 * at key offset 0.
 */
void encrypt_data(void *data, size_t len, const unsigned char *key) {
    unsigned char *d = (unsigned char *)data;
    for (size_t i = 0; i < len; i++) {
        d[i] ^= key[i % 32];
    }
}

int main(void) {
    /* Phase 1: Allocate all chunks */
    for (int i = 0; i < NUM_CHUNKS; i++) {
        chunks[i] = malloc(chunk_sizes[i]);
        memset(chunks[i], 0, chunk_sizes[i]);
    }

    /* Phase 2: Write initial data to all chunks (non-secret) */
    for (int i = 0; i < NUM_CHUNKS; i++) {
        for (size_t j = 0; j < chunk_sizes[i]; j++) {
            ((unsigned char *)chunks[i])[j] = (i * 37 + j * 13 + 0x41) & 0xFF;
        }
    }

    /* Phase 3: Initialize non-encrypted data */

    /* Chunk 0: System banner */
    memset(chunks[0], 0, chunk_sizes[0]);
    strcpy(chunks[0], "HEAP STATE MANAGER v3.1 - CLASSIFIED");
    /* Fill remaining bytes with pattern for integrity verification */
    for (size_t j = strlen("HEAP STATE MANAGER v3.1 - CLASSIFIED") + 1;
         j < chunk_sizes[0]; j++) {
        ((unsigned char *)chunks[0])[j] = (j * 7 + 0x41) & 0xFF;
    }

    /* Chunk 1: System metadata */
    memset(chunks[1], 0, chunk_sizes[1]);
    ((uint64_t *)chunks[1])[0] = NUM_CHUNKS;  /* chunk count */
    ((uint64_t *)chunks[1])[1] = 3;           /* version */
    ((uint64_t *)chunks[1])[2] = 0x42;        /* operational flags */

    /* Chunk 6: Key derivation constant */
    memset(chunks[6], 0, chunk_sizes[6]);
    ((uint64_t *)chunks[6])[0] = 0xDEADBEEFCAFEBABE;
    strcpy((char *)chunks[6] + 8, "KEYPARAMS");
    for (size_t j = 18; j < chunk_sizes[6]; j++) {
        ((unsigned char *)chunks[6])[j] = (j * 3 + 0x77) & 0xFF;
    }

    /* Phase 4: Free chunks 2, 4, 7 (in this order) */
    /* These enter tcache with safe-linking enabled */
    free(chunks[2]);  /* enters tcache[3] (size 0x50 bin) */
    free(chunks[4]);  /* enters tcache[3] (becomes new head) */
    free(chunks[7]);  /* enters tcache[1] (size 0x30 bin) */
    /* NOTE: pointers are NOT zeroed - still accessible for key derivation */

    /* Phase 5: Load classified data fragments into chunks 3, 5, 8.
     *
     * Each fragment is a JSON object: {"part": N, "data": "<fragment>"}
     * After decryption, extract "data" values from parts 1, 2, 3 in order
     * and concatenate to form: FLAG{data1 + data2 + data3}
     *
     * The actual fragment strings were loaded from a secure runtime
     * configuration (/etc/vault/fragments.conf) that is not part of
     * this source distribution.
     */
    /* [classified content loaded at runtime - source redacted] */

    /* Phase 6: Derive key and encrypt the fragments */
    unsigned char key[32];
    derive_key(key);

    encrypt_data(chunks[3], chunk_sizes[3], key);
    encrypt_data(chunks[5], chunk_sizes[5], key);
    encrypt_data(chunks[8], chunk_sizes[8], key);

    /* Phase 7: Memory dump captured here via GDB
     * dump binary memory /app/heap_dump.bin <heap_base> <heap_base+0x600>
     */
    printf("Classified data encrypted. Heap state captured.\n");

    return 0;
}
