/*
 * pipeline.c - Multi-stage cooperative data processing pipeline
 *              using Contiki-NG protothreads. (FIXED VERSION)
 *
 * Build:  gcc -O2 -o /app/pipeline /app/pipeline.c -I/app/include
 * Run:    ./pipeline
 *
 * Pipeline topology (fan-out / fan-in):
 *   Reader -> Transformer -> Splitter
 *                             |-> (chan_even) -> EvenProc -> (chan_em) -|
 *                             |-> (chan_odd)  -> OddProc  -> (chan_om) -|-> Merger -> (chan_out) -> Writer
 *
 * Fixes applied:
 * 1. channel_init: slots semaphore initialized to CHAN_CAP, items to 0
 *    (were swapped).
 * 2. CHAN_SEND: writes to buf[head % CHAN_CAP] not buf[tail % CHAN_CAP].
 * 3. Scheduler: loops until all seven done flags are set.
 * 4. Splitter: replaced switch(val & 1) with if/else to avoid nested
 *    switch conflicting with the PT LC mechanism.
 * 5. Local variables across blocking points declared static (reader fp/val,
 *    transformer val, writer fp).
 * 6. CHAN_RECV: rewritten with EOF-awareness via compound PT_WAIT_UNTIL
 *    condition; returns status to caller.
 * 7. Merger: reimplemented with non-blocking CHAN_TRYRECV to poll both
 *    input channels fairly without deadlocking.
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
 * ============================================================ */
#define CHAN_CAP 4

typedef struct {
    int32_t buf[CHAN_CAP];
    unsigned int head, tail;
    int closed;
    struct pt_sem slots;
    struct pt_sem items;
} channel_t;

/* FIX 1: correct semaphore initialization */
static void channel_init(channel_t *c) {
    memset(c, 0, sizeof(*c));
    PT_SEM_INIT(&c->slots, CHAN_CAP);
    PT_SEM_INIT(&c->items, 0);
}

static void channel_close(channel_t *c) {
    c->closed = 1;
}

/* FIX 2: write to buf[head] not buf[tail] */
#define CHAN_SEND(pt, ch, v) do {                    \
    PT_SEM_WAIT((pt), &(ch)->slots);                \
    (ch)->buf[(ch)->head % CHAN_CAP] = (v);          \
    (ch)->head++;                                    \
    PT_SEM_SIGNAL((pt), &(ch)->items);              \
} while(0)

/* FIX 6: EOF-aware blocking receive with status output.
 * Unblocks when items are available OR when the channel is closed.
 * Sets *status_ptr to 1 on successful receive, 0 on EOF. */
#define CHAN_RECV(pt, ch, pv, status_ptr) do {                       \
    PT_WAIT_UNTIL((pt), PT_SEM_COUNT(&(ch)->items) > 0 ||           \
                        (ch)->closed);                               \
    if (PT_SEM_COUNT(&(ch)->items) > 0) {                           \
        ++(ch)->items.tail;                                         \
        *(pv) = (ch)->buf[(ch)->tail % CHAN_CAP];                   \
        (ch)->tail++;                                                \
        PT_SEM_SIGNAL((pt), &(ch)->slots);                          \
        *(status_ptr) = 1;                                          \
    } else {                                                         \
        *(status_ptr) = 0;                                          \
    }                                                                \
} while(0)

/* FIX 7: Non-blocking receive for multi-channel polling (merger).
 * Checks if data is available without using PT blocking points.
 * Sets *got_ptr to 1 if a value was received, 0 otherwise. */
#define CHAN_TRYRECV(ch, pv, got_ptr) do {                          \
    if (PT_SEM_COUNT(&(ch)->items) > 0) {                          \
        ++(ch)->items.tail;                                        \
        *(pv) = (ch)->buf[(ch)->tail % CHAN_CAP];                  \
        (ch)->tail++;                                               \
        ++(ch)->slots.head;                                         \
        *(got_ptr) = 1;                                             \
    } else {                                                        \
        *(got_ptr) = 0;                                             \
    }                                                               \
} while(0)

/* ============================================================ */

/* Channels */
static channel_t chan_in, chan_xf, chan_even, chan_odd, chan_em, chan_om, chan_out;

/* Protothread structs */
static struct pt pt_reader, pt_xform, pt_splitter;
static struct pt pt_even, pt_odd, pt_merger, pt_writer;

/* Done flags */
static int reader_done, xform_done, splitter_done;
static int even_done, odd_done, merger_done, writer_done;

/* ---- Stage 1: Reader ---- */
static
PT_THREAD(stage_reader(struct pt *pt))
{
    /* FIX 5: static locals */
    static FILE *fp;
    static int32_t val;

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

/* ---- Stage 2: Transformer ---- */
static
PT_THREAD(stage_transformer(struct pt *pt))
{
    /* FIX 5: static local */
    static int32_t val;
    static int ok;

    PT_BEGIN(pt);

    for (;;) {
        CHAN_RECV(pt, &chan_in, &val, &ok);
        if (!ok) break;
        val = ((val & 0xFF) * 7 + 13) & 0xFF;
        CHAN_SEND(pt, &chan_xf, val);
    }

    channel_close(&chan_xf);
    xform_done = 1;

    PT_END(pt);
}

/* ---- Stage 3: Splitter ---- */
static
PT_THREAD(stage_splitter(struct pt *pt))
{
    static int32_t val;
    static int ok;

    PT_BEGIN(pt);

    for (;;) {
        CHAN_RECV(pt, &chan_xf, &val, &ok);
        if (!ok) break;

        /* FIX 4: if/else instead of switch to avoid nested switch
         * conflicting with the PT LC mechanism's outer switch. */
        if ((val & 1) == 0) {
            CHAN_SEND(pt, &chan_even, val);
        } else {
            CHAN_SEND(pt, &chan_odd, val);
        }
    }

    channel_close(&chan_even);
    channel_close(&chan_odd);
    splitter_done = 1;

    PT_END(pt);
}

/* ---- Stage 4a: EvenProc ---- */
static
PT_THREAD(stage_even_proc(struct pt *pt))
{
    static int32_t val;
    static int ok;

    PT_BEGIN(pt);

    for (;;) {
        CHAN_RECV(pt, &chan_even, &val, &ok);
        if (!ok) break;
        val = val * 2;
        CHAN_SEND(pt, &chan_em, val);
    }

    channel_close(&chan_em);
    even_done = 1;

    PT_END(pt);
}

/* ---- Stage 4b: OddProc ---- */
static
PT_THREAD(stage_odd_proc(struct pt *pt))
{
    static int32_t val;
    static int ok;

    PT_BEGIN(pt);

    for (;;) {
        CHAN_RECV(pt, &chan_odd, &val, &ok);
        if (!ok) break;
        val = val + 50;
        CHAN_SEND(pt, &chan_om, val);
    }

    channel_close(&chan_om);
    odd_done = 1;

    PT_END(pt);
}

/* ---- Stage 5: Merger ----
 * FIX 7: Reimplemented with non-blocking CHAN_TRYRECV to drain
 * both input channels (chan_em and chan_om) fairly. A blocking
 * sequential drain would deadlock because the undrained channel's
 * backpressure stalls the upstream splitter, which prevents the
 * drained channel from getting new data. */
static
PT_THREAD(stage_merger(struct pt *pt))
{
    static int32_t val;
    static int got;
    static int em_eof, om_eof;
    static int progress;

    PT_BEGIN(pt);

    em_eof = om_eof = 0;

    for (;;) {
        progress = 0;

        if (!em_eof) {
            CHAN_TRYRECV(&chan_em, &val, &got);
            if (got) {
                progress = 1;
                CHAN_SEND(pt, &chan_out, val);
            } else if (chan_em.closed) {
                em_eof = 1;
            }
        }

        if (!om_eof) {
            CHAN_TRYRECV(&chan_om, &val, &got);
            if (got) {
                progress = 1;
                CHAN_SEND(pt, &chan_out, val);
            } else if (chan_om.closed) {
                om_eof = 1;
            }
        }

        if (em_eof && om_eof) break;

        if (!progress) {
            PT_YIELD(pt);
        }
    }

    channel_close(&chan_out);
    merger_done = 1;

    PT_END(pt);
}

/* ---- Stage 6: Writer ---- */
static
PT_THREAD(stage_writer(struct pt *pt))
{
    static int32_t val;
    /* FIX 5: static local */
    static FILE *fp;
    static int ok;

    PT_BEGIN(pt);

    fp = fopen(OUTPUT_PATH, "w");
    if (!fp) {
        writer_done = 1;
        PT_EXIT(pt);
    }

    for (;;) {
        CHAN_RECV(pt, &chan_out, &val, &ok);
        if (!ok) break;
        fprintf(fp, "%d\n", (int)val);
    }

    fclose(fp);
    writer_done = 1;

    PT_END(pt);
}

/* ---- Scheduler ---- */
/* FIX 3: loop until all stages done */
int main(void)
{
    channel_init(&chan_in);
    channel_init(&chan_xf);
    channel_init(&chan_even);
    channel_init(&chan_odd);
    channel_init(&chan_em);
    channel_init(&chan_om);
    channel_init(&chan_out);

    PT_INIT(&pt_reader);
    PT_INIT(&pt_xform);
    PT_INIT(&pt_splitter);
    PT_INIT(&pt_even);
    PT_INIT(&pt_odd);
    PT_INIT(&pt_merger);
    PT_INIT(&pt_writer);

    reader_done = xform_done = splitter_done = 0;
    even_done = odd_done = merger_done = writer_done = 0;

    while (!reader_done || !xform_done || !splitter_done ||
           !even_done || !odd_done || !merger_done || !writer_done) {
        if (!reader_done)    stage_reader(&pt_reader);
        if (!xform_done)     stage_transformer(&pt_xform);
        if (!splitter_done)  stage_splitter(&pt_splitter);
        if (!even_done)      stage_even_proc(&pt_even);
        if (!odd_done)       stage_odd_proc(&pt_odd);
        if (!merger_done)    stage_merger(&pt_merger);
        if (!writer_done)    stage_writer(&pt_writer);
    }

    return 0;
}
