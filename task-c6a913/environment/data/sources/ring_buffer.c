#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct ring_buf {
    char *data;
    int capacity;
    int write_pos;
    int read_pos;
    int count;
};

struct ring_buf *ring_create(int capacity) {
    struct ring_buf *rb = (struct ring_buf *)malloc(sizeof(struct ring_buf));
    rb->data = (char *)malloc(capacity);
    rb->capacity = capacity;
    rb->write_pos = 0;
    rb->read_pos = 0;
    rb->count = 0;
    return rb;
}

void ring_destroy(struct ring_buf *rb) {
    free(rb->data);
    free(rb);
}

int ring_read(struct ring_buf *rb, char *dst, int len) {
    if (len > rb->count)
        len = rb->count;
    int first_chunk = rb->capacity - rb->read_pos;
    if (first_chunk >= len) {
        memcpy(dst, rb->data + rb->read_pos, len);
    } else {
        memcpy(dst, rb->data + rb->read_pos, first_chunk);
        memcpy(dst + first_chunk, rb->data, len - first_chunk);
    }
    rb->read_pos = (rb->read_pos + len) % rb->capacity;
    rb->count -= len;
    return len;
}

/*
 * ring_write - Write data into the ring buffer
 * @rb: ring buffer instance
 * @src: source data pointer
 * @len: number of bytes to write
 *
 * When data wraps around the end of the circular buffer,
 * the write is split into two memcpy operations covering
 * regions [write_pos..capacity) and [0..remainder).
 *
 * BUG: In the wrap-around case, the first memcpy incorrectly
 * uses 'len' instead of 'first_chunk' as the copy size,
 * writing past the end of the allocated data buffer.
 */
int ring_write(struct ring_buf *rb, const char *src, int len) {
    if (len > rb->capacity - rb->count)
        len = rb->capacity - rb->count;  /* clamp to available space */

    int first_chunk = rb->capacity - rb->write_pos;
    if (first_chunk >= len) {
        memcpy(rb->data + rb->write_pos, src, len);
    } else {
        /* BUG: should copy first_chunk bytes, not len bytes */
        memcpy(rb->data + rb->write_pos, src, len);  /* OVERFLOW WRITE */
        memcpy(rb->data, src + first_chunk, len - first_chunk);
    }
    rb->write_pos = (rb->write_pos + len) % rb->capacity;
    rb->count += len;
    return len;
}

int main(void) {
    struct ring_buf *rb = ring_create(16);
    /* Write 12 bytes to advance write_pos to 12 */
    const char *d1 = "AAAAAAAAAAAA";
    ring_write(rb, d1, 12);
    /* Read 12 bytes to free space (write_pos stays at 12) */
    char tmp[16];
    ring_read(rb, tmp, 12);

    /* Write 10 bytes: first_chunk=4, triggers wrap-around.
     * BUG: first memcpy copies 10 bytes at data+12, overflowing the
     * 16-byte buffer (writes to positions 12..21, valid range 0..15). */
    const char *d2 = "BBBBBBBBBB";
    ring_write(rb, d2, 10);

    printf("Ring buffer count: %d\n", rb->count);
    ring_destroy(rb);
    return 0;
}
