#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct skb_option {
    unsigned char type;
    unsigned char length;
};

struct skb_buf {
    unsigned char *head;
    int total_len;
};

struct skb_buf *skb_alloc(int size) {
    struct skb_buf *skb = (struct skb_buf *)malloc(sizeof(struct skb_buf));
    if (!skb) return NULL;
    skb->head = (unsigned char *)malloc(size);
    if (!skb->head) { free(skb); return NULL; }
    skb->total_len = size;
    return skb;
}

void skb_free(struct skb_buf *skb) {
    if (skb) {
        free(skb->head);
        free(skb);
    }
}

/*
 * parse_skb_options - Parse TLV options from network buffer
 * @skb: socket buffer containing packet data
 * @offset: byte offset where option region begins
 * @opt_len: declared length of the option region
 *
 * Walks the option region parsing { type, length, data } tuples.
 * Returns the number of options successfully parsed.
 */
int parse_skb_options(struct skb_buf *skb, int offset,
                      int opt_len)
{
    int pos = offset;
    int count = 0;

    while (pos < offset + opt_len) {
        struct skb_option *opt = (struct skb_option *)(skb->head + pos);

        if (opt->type == 0) /* end-of-options marker */
            break;

        /* BUG: trusts opt->length without validating against buffer bounds.
         * A crafted packet with opt->length > (skb->total_len - pos - 2)
         * causes heap-buffer-overflow on the memcpy below.
         * Expected TLV format: { type: u8, length: u8, data: u8[length] } */
        unsigned char tmp[256];
        int data_len = opt->length;
        memcpy(tmp, skb->head + pos + 2, data_len);  /* OOB READ HERE */

        pos += 2 + data_len;
        count++;
    }
    return count;
}

int main(void) {
    struct skb_buf *skb = skb_alloc(16);
    if (!skb) return 1;
    memset(skb->head, 0, 16);
    /* Craft a malformed option at offset 4: type=1, length=200 */
    skb->head[4] = 0x01;
    skb->head[5] = 0xc8;  /* 200 decimal - far exceeds remaining buffer */
    int n = parse_skb_options(skb, 4, 12);
    printf("Parsed %d options\n", n);
    skb_free(skb);
    return 0;
}
