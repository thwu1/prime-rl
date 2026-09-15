/*
 * Limit Order Book Matching Engine — Shared Library Implementation
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <inttypes.h>
#include "protocol.h"
#include "types.h"
#include "engine_api.h"

#define VIS __attribute__((visibility("default")))

/* ── Internal data structures ───────────────────────────────────────── */

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

/* ── Constants ──────────────────────────────────────────────────────── */

#define OM_BITS 21
#define OM_SIZE (1u << OM_BITS)
#define OM_MASK (OM_SIZE - 1)

#define LM_BITS 16
#define LM_SIZE (1u << LM_BITS)
#define LM_MASK (LM_SIZE - 1)

#define OUT_BUF_INIT 65536

/* ── Book context ───────────────────────────────────────────────────── */

struct lob_book {
    Order      **order_map;
    PriceLevel **level_map;
    PriceLevel  *buy_head;
    PriceLevel  *sell_head;
    int          buy_depth;
    int          sell_depth;
    FILE        *out_fp;     /* non-NULL during feed processing */
    char        *out_buf;    /* buffer for granular API output  */
    size_t       out_len;
    size_t       out_cap;
};

/* ── Output ─────────────────────────────────────────────────────────── */

static void emit(lob_book *b, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    if (b->out_fp) {
        vfprintf(b->out_fp, fmt, ap);
    } else {
        char tmp[256];
        int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
        if (n > 0) {
            size_t need = (size_t)n;
            if (b->out_len + need + 1 > b->out_cap) {
                size_t nc = (b->out_len + need + 1) * 2;
                if (nc < OUT_BUF_INIT) nc = OUT_BUF_INIT;
                b->out_buf = (char *)realloc(b->out_buf, nc);
                b->out_cap = nc;
            }
            memcpy(b->out_buf + b->out_len, tmp, need);
            b->out_len += need;
            b->out_buf[b->out_len] = '\0';
        }
    }
    va_end(ap);
}

/* ── Hash helpers ───────────────────────────────────────────────────── */

static inline uint32_t h64(uint64_t k) {
    k *= 0x9E3779B97F4A7C15ULL;
    return (uint32_t)(k >> (64 - OM_BITS));
}

static inline uint32_t hlev(uint32_t price, uint8_t side) {
    uint64_t k = ((uint64_t)price << 1) | side;
    k *= 0x9E3779B97F4A7C15ULL;
    return (uint32_t)(k >> (64 - LM_BITS));
}

/* ── Order map ──────────────────────────────────────────────────────── */

static Order *om_find(lob_book *b, uint64_t oid) {
    Order *o = b->order_map[h64(oid) & OM_MASK];
    while (o) { if (o->order_id == oid) return o; o = o->map_next; }
    return NULL;
}

static void om_insert(lob_book *b, Order *o) {
    uint32_t i = h64(o->order_id) & OM_MASK;
    o->map_next = b->order_map[i];
    b->order_map[i] = o;
}

static void om_remove(lob_book *b, Order *o) {
    uint32_t i = h64(o->order_id) & OM_MASK;
    Order **pp = &b->order_map[i];
    while (*pp) { if (*pp == o) { *pp = o->map_next; return; } pp = &(*pp)->map_next; }
}

/* ── Level map ──────────────────────────────────────────────────────── */

static PriceLevel *lm_find(lob_book *b, uint32_t price, uint8_t side) {
    PriceLevel *l = b->level_map[hlev(price, side) & LM_MASK];
    while (l) { if (l->price == price && l->side == side) return l; l = l->map_next; }
    return NULL;
}

static void lm_insert(lob_book *b, PriceLevel *l) {
    uint32_t i = hlev(l->price, l->side) & LM_MASK;
    l->map_next = b->level_map[i];
    b->level_map[i] = l;
}

static void lm_remove(lob_book *b, PriceLevel *l) {
    uint32_t i = hlev(l->price, l->side) & LM_MASK;
    PriceLevel **pp = &b->level_map[i];
    while (*pp) { if (*pp == l) { *pp = l->map_next; return; } pp = &(*pp)->map_next; }
}

/* ── Level list management ──────────────────────────────────────────── */

static PriceLevel *create_level(lob_book *b, uint32_t price, uint8_t side) {
    PriceLevel *l = (PriceLevel *)calloc(1, sizeof(PriceLevel));
    l->price = price; l->side = side;
    lm_insert(b, l);

    if (side == SIDE_BUY) {
        PriceLevel *p = b->buy_head, *prev = NULL;
        while (p && p->price > price) { prev = p; p = p->next_lev; }
        l->next_lev = p; l->prev_lev = prev;
        if (p) p->prev_lev = l;
        if (prev) prev->next_lev = l; else b->buy_head = l;
        b->buy_depth++;
    } else {
        PriceLevel *p = b->sell_head, *prev = NULL;
        while (p && p->price < price) { prev = p; p = p->next_lev; }
        l->next_lev = p; l->prev_lev = prev;
        if (p) p->prev_lev = l;
        if (prev) prev->next_lev = l; else b->sell_head = l;
        b->sell_depth++;
    }
    return l;
}

static void destroy_level(lob_book *b, PriceLevel *l) {
    lm_remove(b, l);
    if (l->side == SIDE_BUY) {
        if (l->prev_lev) l->prev_lev->next_lev = l->next_lev;
        else b->buy_head = l->next_lev;
        if (l->next_lev) l->next_lev->prev_lev = l->prev_lev;
        b->buy_depth--;
    } else {
        if (l->prev_lev) l->prev_lev->next_lev = l->next_lev;
        else b->sell_head = l->next_lev;
        if (l->next_lev) l->next_lev->prev_lev = l->prev_lev;
        b->sell_depth--;
    }
    free(l);
}

/* ── Order helpers ──────────────────────────────────────────────────── */

static void remove_order(lob_book *b, Order *o) {
    PriceLevel *l = o->level;
    if (o->prev) o->prev->next = o->next; else l->head = o->next;
    if (o->next) o->next->prev = o->prev; else l->tail = o->prev;
    l->total_vol -= o->qty;
    om_remove(b, o);
    if (!l->head) destroy_level(b, l);
    free(o);
}

static void add_to_level(Order *o, PriceLevel *l) {
    o->level = l;
    o->prev = l->tail; o->next = NULL;
    if (l->tail) l->tail->next = o; else l->head = o;
    l->tail = o;
    l->total_vol += o->qty;
}

/* ── Matching engine ────────────────────────────────────────────────── */

static void do_add(lob_book *b, uint64_t oid, uint8_t side, uint32_t qty,
                   uint32_t price, uint64_t tid)
{
    if (side == SIDE_BUY) {
        PriceLevel *lev = b->sell_head;
        while (qty > 0 && lev && price >= lev->price) {
            PriceLevel *next_lev = lev->next_lev;
            Order *o = lev->head;
            while (o && qty > 0) {
                Order *onext = o->next;
                if (o->trader_id == tid) { o = onext; continue; }
                uint32_t eq = (qty < o->qty) ? qty : o->qty;
                emit(b, "E %" PRIu64 " %" PRIu64 " %u %u\n",
                     oid, o->order_id, lev->price, eq);
                qty -= eq;
                if (eq >= o->qty) {
                    remove_order(b, o);
                } else {
                    o->qty -= eq;
                    lev->total_vol -= eq;
                }
                o = onext;
            }
            lev = next_lev;
        }
    } else {
        PriceLevel *lev = b->buy_head;
        while (qty > 0 && lev && price <= lev->price) {
            PriceLevel *next_lev = lev->next_lev;
            Order *o = lev->head;
            while (o && qty > 0) {
                Order *onext = o->next;
                if (o->trader_id == tid) { o = onext; continue; }
                uint32_t eq = (qty < o->qty) ? qty : o->qty;
                emit(b, "E %" PRIu64 " %" PRIu64 " %u %u\n",
                     o->order_id, oid, lev->price, eq);
                qty -= eq;
                if (eq >= o->qty) {
                    remove_order(b, o);
                } else {
                    o->qty -= eq;
                    lev->total_vol -= eq;
                }
                o = onext;
            }
            lev = next_lev;
        }
    }

    if (qty > 0) {
        PriceLevel *l = lm_find(b, price, side);
        if (!l) l = create_level(b, price, side);
        Order *o = (Order *)calloc(1, sizeof(Order));
        o->order_id  = oid;
        o->side      = side;
        o->qty       = qty;
        o->price     = price;
        o->trader_id = tid;
        om_insert(b, o);
        add_to_level(o, l);
    }
}

static void do_cancel(lob_book *b, uint64_t oid) {
    Order *o = om_find(b, oid);
    if (o) remove_order(b, o);
}

static void do_reduce(lob_book *b, uint64_t oid, uint32_t rq) {
    Order *o = om_find(b, oid);
    if (!o) return;
    if (rq >= o->qty) {
        remove_order(b, o);
    } else {
        o->level->total_vol -= rq;
        o->qty -= rq;
    }
}

static void do_replace(lob_book *b, uint64_t old_id, uint64_t new_id,
                       uint32_t nq, uint32_t np)
{
    Order *o = om_find(b, old_id);
    if (!o) return;
    uint8_t  side = o->side;
    uint64_t tid  = o->trader_id;
    remove_order(b, o);
    do_add(b, new_id, side, nq, np, tid);
}

/* ── Binary I/O helpers ─────────────────────────────────────────────── */

static inline uint64_t rd64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
static inline uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

/* ═══════════════════════════════════════════════════════════════════════
   Public API
   ═══════════════════════════════════════════════════════════════════════ */

VIS lob_book *lob_book_create(void) {
    lob_book *b = (lob_book *)calloc(1, sizeof(lob_book));
    if (!b) return NULL;
    b->order_map = (Order **)calloc(OM_SIZE, sizeof(Order *));
    b->level_map = (PriceLevel **)calloc(LM_SIZE, sizeof(PriceLevel *));
    if (!b->order_map || !b->level_map) {
        free(b->order_map);
        free(b->level_map);
        free(b);
        return NULL;
    }
    b->out_buf = (char *)malloc(OUT_BUF_INIT);
    b->out_cap = OUT_BUF_INIT;
    b->out_len = 0;
    b->out_buf[0] = '\0';
    return b;
}

VIS void lob_book_destroy(lob_book *b) {
    if (!b) return;
    for (uint32_t i = 0; i < OM_SIZE; i++) {
        Order *o = b->order_map[i];
        while (o) { Order *n = o->map_next; free(o); o = n; }
    }
    for (uint32_t i = 0; i < LM_SIZE; i++) {
        PriceLevel *l = b->level_map[i];
        while (l) { PriceLevel *n = l->map_next; free(l); l = n; }
    }
    free(b->order_map);
    free(b->level_map);
    free(b->out_buf);
    free(b);
}

VIS int lob_process_feed(lob_book *b, const uint8_t *data, size_t len,
                         const char *output_path)
{
    FILE *fp = fopen(output_path, "w");
    if (!fp) return 1;
    setvbuf(fp, NULL, _IOFBF, 1 << 16);
    b->out_fp = fp;

    const uint8_t *ptr = data, *end = data + len;
    while (ptr < end) {
        uint8_t type = *ptr++;
        switch (type) {
        case MSG_ADD_ORDER: {
            uint64_t oid = rd64(ptr); ptr += 8;
            uint8_t  s   = *ptr++;
            uint32_t qty = rd32(ptr); ptr += 4;
            uint32_t px  = rd32(ptr); ptr += 4;
            uint64_t tid = rd64(ptr); ptr += 8;
            do_add(b, oid, s, qty, px, tid);
            break;
        }
        case MSG_CANCEL: {
            uint64_t oid = rd64(ptr); ptr += 8;
            do_cancel(b, oid);
            break;
        }
        case MSG_REDUCE: {
            uint64_t oid = rd64(ptr); ptr += 8;
            uint32_t rq  = rd32(ptr); ptr += 4;
            do_reduce(b, oid, rq);
            break;
        }
        case MSG_REPLACE: {
            uint64_t old_id = rd64(ptr); ptr += 8;
            uint64_t new_id = rd64(ptr); ptr += 8;
            uint32_t nq     = rd32(ptr); ptr += 4;
            uint32_t np     = rd32(ptr); ptr += 4;
            do_replace(b, old_id, new_id, nq, np);
            break;
        }
        case MSG_QUERY: {
            uint64_t qid   = rd64(ptr); ptr += 8;
            uint8_t  qt    = *ptr++;
            uint64_t param = rd64(ptr); ptr += 8;
            switch (qt) {
            case QUERY_BEST_BID:
                emit(b, "Q %" PRIu64 " %u\n", qid,
                     b->buy_head ? b->buy_head->price : 0);
                break;
            case QUERY_BEST_OFFER:
                emit(b, "Q %" PRIu64 " %u\n", qid,
                     b->sell_head ? b->sell_head->price : 0);
                break;
            case QUERY_VOL_AT_PRICE: {
                uint32_t price = (uint32_t)param, vol = 0;
                PriceLevel *bl = lm_find(b, price, SIDE_BUY);
                if (bl) vol += bl->total_vol;
                PriceLevel *sl = lm_find(b, price, SIDE_SELL);
                if (sl) vol += sl->total_vol;
                emit(b, "Q %" PRIu64 " %u\n", qid, vol);
                break;
            }
            case QUERY_BOOK_DEPTH:
                emit(b, "Q %" PRIu64 " %d %d\n", qid, b->buy_depth, b->sell_depth);
                break;
            case QUERY_ORDER_INFO: {
                Order *o = om_find(b, param);
                if (o)
                    emit(b, "Q %" PRIu64 " %u %u %u\n",
                         qid, (unsigned)o->side, o->price, o->qty);
                else
                    emit(b, "Q %" PRIu64 " NONE\n", qid);
                break;
            }
            }
            break;
        }
        default:
            fclose(fp);
            b->out_fp = NULL;
            return 1;
        }
    }

    fclose(fp);
    b->out_fp = NULL;
    return 0;
}

VIS void lob_add_order(lob_book *b, uint64_t order_id, uint8_t side,
                       uint32_t qty, uint32_t price, uint64_t trader_id)
{
    do_add(b, order_id, side, qty, price, trader_id);
}

VIS void lob_cancel_order(lob_book *b, uint64_t order_id) {
    do_cancel(b, order_id);
}

VIS void lob_reduce_order(lob_book *b, uint64_t order_id, uint32_t reduce_qty) {
    do_reduce(b, order_id, reduce_qty);
}

VIS void lob_replace_order(lob_book *b, uint64_t old_id, uint64_t new_id,
                           uint32_t new_qty, uint32_t new_price)
{
    do_replace(b, old_id, new_id, new_qty, new_price);
}

VIS uint32_t lob_best_bid(const lob_book *b) {
    return b->buy_head ? b->buy_head->price : 0;
}

VIS uint32_t lob_best_offer(const lob_book *b) {
    return b->sell_head ? b->sell_head->price : 0;
}

VIS uint32_t lob_volume_at_price(const lob_book *b, uint32_t price) {
    lob_book *mb = (lob_book *)b;
    uint32_t vol = 0;
    PriceLevel *bl = lm_find(mb, price, SIDE_BUY);
    if (bl) vol += bl->total_vol;
    PriceLevel *sl = lm_find(mb, price, SIDE_SELL);
    if (sl) vol += sl->total_vol;
    return vol;
}

VIS void lob_book_depth(const lob_book *b, int *buy_levels, int *sell_levels) {
    *buy_levels = b->buy_depth;
    *sell_levels = b->sell_depth;
}

VIS int lob_order_info(const lob_book *b, uint64_t order_id,
                       uint8_t *side_out, uint32_t *price_out, uint32_t *qty_out)
{
    Order *o = om_find((lob_book *)b, order_id);
    if (!o) return 0;
    *side_out  = o->side;
    *price_out = o->price;
    *qty_out   = o->qty;
    return 1;
}

VIS const char *lob_get_output(const lob_book *b) {
    if (b->out_len == 0) return NULL;
    return b->out_buf;
}

VIS void lob_clear_output(lob_book *b) {
    b->out_len = 0;
    b->out_buf[0] = '\0';
}
