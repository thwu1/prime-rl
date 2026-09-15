/*
 * Limit Order Book Matching Engine
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include "protocol.h"
#include "types.h"

/* ── Data structures ─────────────────────────────────────────────── */

typedef struct Order {
    uint64_t order_id;
    uint8_t  side;
    uint32_t qty;
    uint32_t price;
    uint64_t trader_id;
    struct Order *prev, *next;       /* within price level  */
    struct PriceLevel *level;        /* parent level        */
    struct Order *map_next;          /* order hash chain    */
} Order;

typedef struct PriceLevel {
    uint32_t price;
    uint8_t  side;
    uint32_t total_vol;
    Order   *head, *tail;
    struct PriceLevel *prev_lev, *next_lev;  /* sorted list  */
    struct PriceLevel *map_next;              /* level hash   */
} PriceLevel;

/* ── Hash maps ───────────────────────────────────────────────────── */

#define OM_BITS 21
#define OM_SIZE (1u << OM_BITS)
#define OM_MASK (OM_SIZE - 1)
static Order *order_map[OM_SIZE];

#define LM_BITS 16
#define LM_SIZE (1u << LM_BITS)
#define LM_MASK (LM_SIZE - 1)
static PriceLevel *level_map[LM_SIZE];

/* Sorted level lists */
static PriceLevel *buy_head;    /* descending by price */
static PriceLevel *sell_head;   /* ascending  by price */
static int buy_depth, sell_depth;

/* Output */
static FILE *out_fp;

/* ── Hash helpers ────────────────────────────────────────────────── */

static inline uint32_t h64(uint64_t k) {
    k *= 0x9E3779B97F4A7C15ULL;
    return (uint32_t)(k >> (64 - OM_BITS));
}

static inline uint32_t hlev(uint32_t price, uint8_t side) {
    uint64_t k = ((uint64_t)price << 1) | side;
    k *= 0x9E3779B97F4A7C15ULL;
    return (uint32_t)(k >> (64 - LM_BITS));
}

/* ── Order map ───────────────────────────────────────────────────── */

static Order *om_find(uint64_t oid) {
    Order *o = order_map[h64(oid) & OM_MASK];
    while (o) { if (o->order_id == oid) return o; o = o->map_next; }
    return NULL;
}
static void om_insert(Order *o) {
    uint32_t i = h64(o->order_id) & OM_MASK;
    o->map_next = order_map[i]; order_map[i] = o;
}
static void om_remove(Order *o) {
    uint32_t i = h64(o->order_id) & OM_MASK;
    Order **pp = &order_map[i];
    while (*pp) { if (*pp == o) { *pp = o->map_next; return; } pp = &(*pp)->map_next; }
}

/* ── Level map ───────────────────────────────────────────────────── */

static PriceLevel *lm_find(uint32_t price, uint8_t side) {
    PriceLevel *l = level_map[hlev(price, side) & LM_MASK];
    while (l) { if (l->price == price && l->side == side) return l; l = l->map_next; }
    return NULL;
}
static void lm_insert(PriceLevel *l) {
    uint32_t i = hlev(l->price, l->side) & LM_MASK;
    l->map_next = level_map[i]; level_map[i] = l;
}
static void lm_remove(PriceLevel *l) {
    uint32_t i = hlev(l->price, l->side) & LM_MASK;
    PriceLevel **pp = &level_map[i];
    while (*pp) { if (*pp == l) { *pp = l->map_next; return; } pp = &(*pp)->map_next; }
}

/* ── Level list management ───────────────────────────────────────── */

static PriceLevel *create_level(uint32_t price, uint8_t side) {
    PriceLevel *l = (PriceLevel *)calloc(1, sizeof(PriceLevel));
    l->price = price; l->side = side;
    lm_insert(l);

    if (side == SIDE_BUY) {
        PriceLevel *p = buy_head, *prev = NULL;
        while (p && p->price > price) { prev = p; p = p->next_lev; }
        l->next_lev = p; l->prev_lev = prev;
        if (p) p->prev_lev = l;
        if (prev) prev->next_lev = l; else buy_head = l;
        buy_depth++;
    } else {
        PriceLevel *p = sell_head, *prev = NULL;
        while (p && p->price < price) { prev = p; p = p->next_lev; }
        l->next_lev = p; l->prev_lev = prev;
        if (p) p->prev_lev = l;
        if (prev) prev->next_lev = l; else sell_head = l;
        sell_depth++;
    }
    return l;
}

static void destroy_level(PriceLevel *l) {
    lm_remove(l);
    if (l->side == SIDE_BUY) {
        if (l->prev_lev) l->prev_lev->next_lev = l->next_lev;
        else buy_head = l->next_lev;
        if (l->next_lev) l->next_lev->prev_lev = l->prev_lev;
        buy_depth--;
    } else {
        if (l->prev_lev) l->prev_lev->next_lev = l->next_lev;
        else sell_head = l->next_lev;
        if (l->next_lev) l->next_lev->prev_lev = l->prev_lev;
        sell_depth--;
    }
    free(l);
}

/* ── Order helpers ───────────────────────────────────────────────── */

static void remove_order(Order *o) {
    PriceLevel *l = o->level;
    if (o->prev) o->prev->next = o->next; else l->head = o->next;
    if (o->next) o->next->prev = o->prev; else l->tail = o->prev;
    l->total_vol -= o->qty;
    om_remove(o);
    if (!l->head) destroy_level(l);
    free(o);
}

static void add_to_level(Order *o, PriceLevel *l) {
    o->level = l;
    o->prev = l->tail; o->next = NULL;
    if (l->tail) l->tail->next = o; else l->head = o;
    l->tail = o;
    l->total_vol += o->qty;
}

/* ── Matching engine ─────────────────────────────────────────────── */

static void process_add(uint64_t oid, uint8_t side, uint32_t qty,
                        uint32_t price, uint64_t tid)
{
    if (side == SIDE_BUY) {
        /* Match against sell side (ascending price) */
        PriceLevel *lev = sell_head;
        while (qty > 0 && lev && price >= lev->price) {
            PriceLevel *next_lev = lev->next_lev;
            Order *o = lev->head;
            while (o && qty > 0) {
                Order *onext = o->next;
                if (o->trader_id == tid) { o = onext; continue; } /* STP */
                uint32_t eq = (qty < o->qty) ? qty : o->qty;
                fprintf(out_fp, "E %" PRIu64 " %" PRIu64 " %u %u\n",
                        oid, o->order_id, lev->price, eq);
                qty -= eq;
                if (eq >= o->qty) {
                    remove_order(o);
                } else {
                    o->qty -= eq;
                    lev->total_vol -= eq;
                }
                o = onext;
            }
            lev = next_lev;
        }
    } else {
        /* Match against buy side (descending price) */
        PriceLevel *lev = buy_head;
        while (qty > 0 && lev && price <= lev->price) {
            PriceLevel *next_lev = lev->next_lev;
            Order *o = lev->head;
            while (o && qty > 0) {
                Order *onext = o->next;
                if (o->trader_id == tid) { o = onext; continue; }
                uint32_t eq = (qty < o->qty) ? qty : o->qty;
                fprintf(out_fp, "E %" PRIu64 " %" PRIu64 " %u %u\n",
                        o->order_id, oid, lev->price, eq);
                qty -= eq;
                if (eq >= o->qty) {
                    remove_order(o);
                } else {
                    o->qty -= eq;
                    lev->total_vol -= eq;
                }
                o = onext;
            }
            lev = next_lev;
        }
    }

    /* Queue remainder */
    if (qty > 0) {
        PriceLevel *l = lm_find(price, side);
        if (!l) l = create_level(price, side);
        Order *o = (Order *)calloc(1, sizeof(Order));
        o->order_id  = oid;
        o->side      = side;
        o->qty       = qty;
        o->price     = price;
        o->trader_id = tid;
        om_insert(o);
        add_to_level(o, l);
    }
}

static void process_cancel(uint64_t oid) {
    Order *o = om_find(oid);
    if (o) remove_order(o);
}

static void process_reduce(uint64_t oid, uint32_t rq) {
    Order *o = om_find(oid);
    if (!o) return;
    if (rq >= o->qty) {
        remove_order(o);
    } else {
        o->level->total_vol -= rq;
        o->qty -= rq;
    }
}

static void process_replace(uint64_t old_id, uint64_t new_id,
                            uint32_t nq, uint32_t np)
{
    Order *o = om_find(old_id);
    if (!o) return;
    uint8_t  side = o->side;
    uint64_t tid  = o->trader_id;
    remove_order(o);
    process_add(new_id, side, nq, np, tid);
}

static void process_query(uint64_t qid, uint8_t qtype, uint64_t param) {
    switch (qtype) {
    case QUERY_BEST_BID:
        fprintf(out_fp, "Q %" PRIu64 " %u\n", qid,
                buy_head ? buy_head->price : 0);
        break;
    case QUERY_BEST_OFFER:
        fprintf(out_fp, "Q %" PRIu64 " %u\n", qid,
                sell_head ? sell_head->price : 0);
        break;
    case QUERY_VOL_AT_PRICE: {
        uint32_t price = (uint32_t)param, vol = 0;
        PriceLevel *bl = lm_find(price, SIDE_BUY);
        if (bl) vol += bl->total_vol;
        PriceLevel *sl = lm_find(price, SIDE_SELL);
        if (sl) vol += sl->total_vol;
        fprintf(out_fp, "Q %" PRIu64 " %u\n", qid, vol);
        break;
    }
    case QUERY_BOOK_DEPTH:
        fprintf(out_fp, "Q %" PRIu64 " %d %d\n", qid, buy_depth, sell_depth);
        break;
    case QUERY_ORDER_INFO: {
        Order *o = om_find(param);
        if (o)
            fprintf(out_fp, "Q %" PRIu64 " %u %u %u\n",
                    qid, (unsigned)o->side, o->price, o->qty);
        else
            fprintf(out_fp, "Q %" PRIu64 " NONE\n", qid);
        break;
    }
    }
}

/* ── Binary I/O helpers ──────────────────────────────────────────── */

static inline uint64_t rd64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
static inline uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

/* ── main ────────────────────────────────────────────────────────── */

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input.bin> <output.txt>\n", argv[0]);
        return 1;
    }

    FILE *in_fp = fopen(argv[1], "rb");
    if (!in_fp) { perror("open input"); return 1; }
    out_fp = fopen(argv[2], "w");
    if (!out_fp) { perror("open output"); fclose(in_fp); return 1; }
    setvbuf(out_fp, NULL, _IOFBF, 1 << 16);

    /* Slurp entire input */
    fseek(in_fp, 0, SEEK_END);
    long fsz = ftell(in_fp);
    fseek(in_fp, 0, SEEK_SET);
    uint8_t *data = (uint8_t *)malloc((size_t)fsz);
    if (!data) { perror("malloc"); return 1; }
    if ((long)fread(data, 1, (size_t)fsz, in_fp) != fsz) {
        perror("fread"); return 1;
    }
    fclose(in_fp);

    const uint8_t *ptr = data, *end = data + fsz;
    while (ptr < end) {
        uint8_t type = *ptr++;
        switch (type) {
        case MSG_ADD_ORDER: {
            uint64_t oid = rd64(ptr);  ptr += 8;
            uint8_t  s   = *ptr++;
            uint32_t qty = rd32(ptr);  ptr += 4;
            uint32_t px  = rd32(ptr);  ptr += 4;
            uint64_t tid = rd64(ptr);  ptr += 8;
            process_add(oid, s, qty, px, tid);
            break;
        }
        case MSG_CANCEL: {
            uint64_t oid = rd64(ptr);  ptr += 8;
            process_cancel(oid);
            break;
        }
        case MSG_REDUCE: {
            uint64_t oid = rd64(ptr);  ptr += 8;
            uint32_t rq  = rd32(ptr);  ptr += 4;
            process_reduce(oid, rq);
            break;
        }
        case MSG_REPLACE: {
            uint64_t old_id = rd64(ptr); ptr += 8;
            uint64_t new_id = rd64(ptr); ptr += 8;
            uint32_t nq     = rd32(ptr); ptr += 4;
            uint32_t np     = rd32(ptr); ptr += 4;
            process_replace(old_id, new_id, nq, np);
            break;
        }
        case MSG_QUERY: {
            uint64_t qid   = rd64(ptr); ptr += 8;
            uint8_t  qt    = *ptr++;
            uint64_t param = rd64(ptr); ptr += 8;
            process_query(qid, qt, param);
            break;
        }
        default:
            fprintf(stderr, "Unknown message type 0x%02x at offset %ld\n",
                    type, (long)(ptr - 1 - data));
            free(data); fclose(out_fp);
            return 1;
        }
    }

    free(data);
    fclose(out_fp);
    return 0;
}
