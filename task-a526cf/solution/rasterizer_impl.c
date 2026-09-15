#include "rasterizer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>


/* ── Buffer helpers ─────────────────────────────────────────────── */

void raster_init(raster_buf_t *rb) {
    rb->cap = 4096;
    rb->buf = malloc(rb->cap);
    rb->len = 0;
}

void raster_free(raster_buf_t *rb) {
    free(rb->buf);
    rb->buf = NULL;
    rb->len = rb->cap = 0;
}

static void rb_grow(raster_buf_t *rb, size_t need) {
    if (rb->len + need <= rb->cap) return;
    while (rb->len + need > rb->cap) rb->cap *= 2;
    rb->buf = realloc(rb->buf, rb->cap);
}

static void rb_put(raster_buf_t *rb, const char *s, size_t n) {
    rb_grow(rb, n);
    memcpy(rb->buf + rb->len, s, n);
    rb->len += n;
}

static void rb_putf(raster_buf_t *rb, const char *fmt, ...) {
    char tmp[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n > 0) rb_put(rb, tmp, (size_t)n);
}

/* ── SGR state tracker ──────────────────────────────────────────── */

typedef struct {
    int fg_r, fg_g, fg_b;
    int bg_r, bg_g, bg_b;
    bool fg_def, bg_def;
    uint16_t style;
} sgr_t;

static sgr_t sgr_default(void) {
    return (sgr_t){
        .fg_r = -1, .fg_g = -1, .fg_b = -1,
        .bg_r = -1, .bg_g = -1, .bg_b = -1,
        .fg_def = true, .bg_def = true,
        .style = 0
    };
}

static bool is_trailing_blank(const composited_cell_t *c) {
    return (c->egc[0] == ' ' || c->egc[0] == '\0') &&
           c->fg_default && c->bg_default && c->style == 0;
}

static bool cell_eq(const composited_cell_t *a, const composited_cell_t *b) {
    if (a->egc[0] != b->egc[0]) return false;
    if (a->fg_default != b->fg_default) return false;
    if (!a->fg_default &&
        (a->fg_r != b->fg_r || a->fg_g != b->fg_g || a->fg_b != b->fg_b))
        return false;
    if (a->bg_default != b->bg_default) return false;
    if (!a->bg_default &&
        (a->bg_r != b->bg_r || a->bg_g != b->bg_g || a->bg_b != b->bg_b))
        return false;
    return a->style == b->style;
}

/*
 * Emit the minimal SGR sequence to transition from the current
 * drawing state (*st) to the attributes of cell *c.
 * Updates *st to reflect the new state.
 */
static void emit_transition(raster_buf_t *rb, sgr_t *st,
                            const composited_cell_t *c) {
    /* Determine what needs to change */
    bool chg_fg = false, chg_bg = false;

    if (c->fg_default) {
        if (!st->fg_def) chg_fg = true;
    } else {
        if (st->fg_def || st->fg_r != c->fg_r ||
            st->fg_g != c->fg_g || st->fg_b != c->fg_b)
            chg_fg = true;
    }

    if (c->bg_default) {
        if (!st->bg_def) chg_bg = true;
    } else {
        if (st->bg_def || st->bg_r != c->bg_r ||
            st->bg_g != c->bg_g || st->bg_b != c->bg_b)
            chg_bg = true;
    }

    bool chg_sty = (st->style != c->style);

    if (!chg_fg && !chg_bg && !chg_sty) return;

    /* Count style bits that need to turn off to decide if reset helps */
    uint16_t off_bits = st->style & ~c->style;
    int n_off = 0;
    if (off_bits & 0x0001) n_off++;   /* STRUCK */
    if (off_bits & 0x0002) n_off++;   /* BOLD */
    if (off_bits & 0x000C) n_off++;   /* UNDERLINE/UNDERCURL */
    if (off_bits & 0x0010) n_off++;   /* ITALIC */

    bool do_rst = (n_off >= 2);

    /* Build SGR parameter string */
    char buf[256];
    int pos = 0;
    bool first = true;

    #define P(...) do { \
        if (!first) buf[pos++] = ';'; \
        pos += snprintf(buf + pos, sizeof(buf) - (size_t)pos, __VA_ARGS__); \
        first = false; \
    } while(0)

    if (do_rst) {
        P("0");
        st->fg_def = true;  st->bg_def = true;
        st->fg_r = st->fg_g = st->fg_b = -1;
        st->bg_r = st->bg_g = st->bg_b = -1;
        st->style = 0;
        chg_fg = !c->fg_default;
        chg_bg = !c->bg_default;
    }

    /* style on */
    if ((c->style & 0x0002) && !(st->style & 0x0002)) P("1");
    if ((c->style & 0x0010) && !(st->style & 0x0010)) P("3");
    if ((c->style & 0x000C) && !(st->style & 0x000C)) P("4");
    if ((c->style & 0x0001) && !(st->style & 0x0001)) P("9");

    /* style off (only without reset — reset already cleared them) */
    if (!do_rst) {
        if (!(c->style & 0x0002) && (st->style & 0x0002)) P("22");
        if (!(c->style & 0x0010) && (st->style & 0x0010)) P("23");
        if (!(c->style & 0x000C) && (st->style & 0x000C)) P("24");
        if (!(c->style & 0x0001) && (st->style & 0x0001)) P("29");
    }

    /* foreground */
    if (chg_fg) {
        if (c->fg_default) { P("39"); }
        else { P("38;2;%d;%d;%d", c->fg_r, c->fg_g, c->fg_b); }
    }

    /* background */
    if (chg_bg) {
        if (c->bg_default) { P("49"); }
        else { P("48;2;%d;%d;%d", c->bg_r, c->bg_g, c->bg_b); }
    }

    #undef P

    if (pos > 0) {
        rb_put(rb, "\033[", 2);
        rb_put(rb, buf, (size_t)pos);
        rb_put(rb, "m", 1);
    }

    /* Update state */
    st->fg_r = c->fg_r; st->fg_g = c->fg_g; st->fg_b = c->fg_b;
    st->bg_r = c->bg_r; st->bg_g = c->bg_g; st->bg_b = c->bg_b;
    st->fg_def = c->fg_default;
    st->bg_def = c->bg_default;
    st->style = c->style;
}

/* ── Full render ────────────────────────────────────────────────── */

void rasterize_full(const composited_cell_t *cells, int rows, int cols,
                    raster_buf_t *out) {
    rb_put(out, "\033[0m", 4);
    sgr_t st = sgr_default();

    for (int y = 0; y < rows; y++) {
        /* find last non-trailing-blank cell */
        int last = -1;
        for (int x = cols - 1; x >= 0; x--) {
            if (!is_trailing_blank(&cells[y * cols + x])) {
                last = x;
                break;
            }
        }
        if (last < 0) continue;

        rb_putf(out, "\033[%d;1H", y + 1);

        for (int x = 0; x <= last; x++) {
            const composited_cell_t *c = &cells[y * cols + x];
            emit_transition(out, &st, c);
            char ch = (c->egc[0] != '\0') ? c->egc[0] : ' ';
            rb_put(out, &ch, 1);
        }
    }

    rb_put(out, "\033[0m", 4);
}

/* ── Diff render ────────────────────────────────────────────────── */

void rasterize_diff(const composited_cell_t *prev,
                    const composited_cell_t *curr,
                    int rows, int cols,
                    raster_buf_t *out) {
    rb_put(out, "\033[0m", 4);
    sgr_t st = sgr_default();

    int cy = -1, cx = -1;  /* virtual cursor position */

    for (int y = 0; y < rows; y++) {
        for (int x = 0; x < cols; x++) {
            int idx = y * cols + x;
            if (cell_eq(&prev[idx], &curr[idx])) continue;

            /* Position cursor if not already at (y, x) */
            if (cy != y || cx != x)
                rb_putf(out, "\033[%d;%dH", y + 1, x + 1);

            emit_transition(out, &st, &curr[idx]);
            char ch = (curr[idx].egc[0] != '\0') ? curr[idx].egc[0] : ' ';
            rb_put(out, &ch, 1);

            cy = y;
            cx = x + 1;
        }
    }

    rb_put(out, "\033[0m", 4);
}
