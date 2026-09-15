/*
 * pipeline.c - Multi-stage cooperative data processing pipeline
 *              using Contiki-NG protothreads.
 *
 * Build:  gcc -O2 -o /app/pipeline /app/pipeline.c -I/app/include
 * Run:    ./pipeline
 *
 * Reads 32-bit little-endian signed integers from /app/input.dat,
 * processes through seven protothread stages connected by bounded
 * channels, writes results to /app/output.dat.
 *
 * Pipeline topology (fan-out / fan-in):
 *   Reader -> Transformer -> Splitter
 *                             |-> (chan_even) -> EvenProc -> (chan_em) -|
 *                             |-> (chan_odd)  -> OddProc  -> (chan_om) -|-> Merger -> (chan_out) -> Writer
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "pt.h"
#include "pt-sem.h"

#define INPUT_PATH  "/app/input.dat"
#define OUTPUT_PATH "/app/output.dat"

/* ============================================================
 * Bounded Channel (FIFO) for inter-protothread communication.
 * Capacity: CHAN_CAP items. Uses pt_sem for synchronization.
 * ============================================================ */
#define CHAN_CAP 4

typedef struct {
    int32_t buf[CHAN_CAP];
    unsigned int head, tail;
    int closed;
    struct pt_sem slots;   /* counts free slots (decremented on send) */
    struct pt_sem items;   /* counts available items (decremented on recv) */
} channel_t;

static void channel_init(channel_t *c) {
    memset(c, 0, sizeof(*c));
    PT_SEM_INIT(&c->items, CHAN_CAP);
    PT_SEM_INIT(&c->slots, 0);
}

static void channel_close(channel_t *c) {
    c->closed = 1;
}

/* Send a value into the channel. Blocks the protothread when full. */
#define CHAN_SEND(pt, ch, v) do {                    \
    PT_SEM_WAIT((pt), &(ch)->slots);                \
    (ch)->buf[(ch)->tail % CHAN_CAP] = (v);          \
    (ch)->head++;                                    \
    PT_SEM_SIGNAL((pt), &(ch)->items);              \
} while(0)

/* Receive a value from the channel. Blocks the protothread when empty. */
#define CHAN_RECV(pt, ch, pv) do {                   \
    PT_SEM_WAIT((pt), &(ch)->items);                \
    *(pv) = (ch)->buf[(ch)->tail % CHAN_CAP];        \
    (ch)->tail++;                                    \
    PT_SEM_SIGNAL((pt), &(ch)->slots);              \
} while(0)

/* ============================================================ */

/* Channels */
static channel_t chan_in;    /* reader -> transformer */
static channel_t chan_xf;    /* transformer -> splitter */
static channel_t chan_even;  /* splitter -> even_proc */
static channel_t chan_odd;   /* splitter -> odd_proc */
static channel_t chan_em;    /* even_proc -> merger */
static channel_t chan_om;    /* odd_proc -> merger */
static channel_t chan_out;   /* merger -> writer */

/* Protothread structs */
static struct pt pt_reader, pt_xform, pt_splitter;
static struct pt pt_even, pt_odd, pt_merger, pt_writer;

/* Done flags */
static int reader_done, xform_done, splitter_done;
static int even_done, odd_done, merger_done, writer_done;

/* ---- Stage 1: Reader ----
 * Reads int32_t values from input.dat and sends them into chan_in. */
static
PT_THREAD(stage_reader(struct pt *pt))
{
    FILE *fp;
    int32_t val;

    PT_BEGIN(pt);

    fp = fopen(INPUT_PATH, "rb");
    if (!fp) {
        channel_close(&chan_in);
        reader_done = 1;
        PT_EXIT(pt);
    }

    while (fread(&val, sizeof(val), 1, fp) == 1) {
        CHAN_SEND(pt, &chan_in, val);
    }

    fclose(fp);
    channel_close(&chan_in);
    reader_done = 1;

    PT_END(pt);
}

/* ---- Stage 2: Transformer ----
 * Applies val = ((val & 0xFF) * 7 + 13) & 0xFF to each value. */
static
PT_THREAD(stage_transformer(struct pt *pt))
{
    int32_t val;

    PT_BEGIN(pt);

    while (!chan_in.closed || PT_SEM_COUNT(&chan_in.items) > 0) {
        CHAN_RECV(pt, &chan_in, &val);
        val = ((val & 0xFF) * 7 + 13) & 0xFF;
        CHAN_SEND(pt, &chan_xf, val);
    }

    channel_close(&chan_xf);
    xform_done = 1;

    PT_END(pt);
}

/* ---- Stage 3: Splitter ----
 * Routes even values (val & 1 == 0) to chan_even,
 * odd values (val & 1 == 1) to chan_odd. */
static
PT_THREAD(stage_splitter(struct pt *pt))
{
    static int32_t val;

    PT_BEGIN(pt);

    while (!chan_xf.closed || PT_SEM_COUNT(&chan_xf.items) > 0) {
        CHAN_RECV(pt, &chan_xf, &val);

        switch (val & 1) {
            case 0:
                CHAN_SEND(pt, &chan_even, val);
                break;
            case 1:
                CHAN_SEND(pt, &chan_odd, val);
                break;
        }
    }

    channel_close(&chan_even);
    channel_close(&chan_odd);
    splitter_done = 1;

    PT_END(pt);
}

/* ---- Stage 4a: EvenProc ----
 * Processes even-routed values: val = val * 2 */
static
PT_THREAD(stage_even_proc(struct pt *pt))
{
    static int32_t val;

    PT_BEGIN(pt);

    while (!chan_even.closed || PT_SEM_COUNT(&chan_even.items) > 0) {
        CHAN_RECV(pt, &chan_even, &val);
        val = val * 2;
        CHAN_SEND(pt, &chan_em, val);
    }

    channel_close(&chan_em);
    even_done = 1;

    PT_END(pt);
}

/* ---- Stage 4b: OddProc ----
 * Processes odd-routed values: val = val + 50 */
static
PT_THREAD(stage_odd_proc(struct pt *pt))
{
    static int32_t val;

    PT_BEGIN(pt);

    while (!chan_odd.closed || PT_SEM_COUNT(&chan_odd.items) > 0) {
        CHAN_RECV(pt, &chan_odd, &val);
        val = val + 50;
        CHAN_SEND(pt, &chan_om, val);
    }

    channel_close(&chan_om);
    odd_done = 1;

    PT_END(pt);
}

/* ---- Stage 5: Merger ----
 * Merges values from chan_em and chan_om into chan_out. */
static
PT_THREAD(stage_merger(struct pt *pt))
{
    static int32_t val;

    PT_BEGIN(pt);

    /* Drain the even-proc output channel. */
    while (!chan_em.closed || PT_SEM_COUNT(&chan_em.items) > 0) {
        CHAN_RECV(pt, &chan_em, &val);
        CHAN_SEND(pt, &chan_out, val);
    }

    channel_close(&chan_out);
    merger_done = 1;

    PT_END(pt);
}

/* ---- Stage 6: Writer ----
 * Writes each value as a decimal line to output.dat. */
static
PT_THREAD(stage_writer(struct pt *pt))
{
    static int32_t val;
    FILE *fp;

    PT_BEGIN(pt);

    fp = fopen(OUTPUT_PATH, "w");
    if (!fp) {
        writer_done = 1;
        PT_EXIT(pt);
    }

    while (!chan_out.closed || PT_SEM_COUNT(&chan_out.items) > 0) {
        CHAN_RECV(pt, &chan_out, &val);
        fprintf(fp, "%d\n", (int)val);
    }

    fclose(fp);
    writer_done = 1;

    PT_END(pt);
}

/* ---- Main / Scheduler ---- */
int main(void)
{
    /* Initialize all channels */
    channel_init(&chan_in);
    channel_init(&chan_xf);
    channel_init(&chan_even);
    channel_init(&chan_odd);
    channel_init(&chan_em);
    channel_init(&chan_om);
    channel_init(&chan_out);

    /* Initialize protothread structs */
    PT_INIT(&pt_reader);
    PT_INIT(&pt_xform);
    PT_INIT(&pt_splitter);
    PT_INIT(&pt_even);
    PT_INIT(&pt_odd);
    PT_INIT(&pt_merger);
    PT_INIT(&pt_writer);

    reader_done = xform_done = splitter_done = 0;
    even_done = odd_done = merger_done = writer_done = 0;

    /* Drive each stage. */
    stage_reader(&pt_reader);
    stage_transformer(&pt_xform);
    stage_splitter(&pt_splitter);
    stage_even_proc(&pt_even);
    stage_odd_proc(&pt_odd);
    stage_merger(&pt_merger);
    stage_writer(&pt_writer);

    return 0;
}
