
/*
 * Reference implementation of a VT/ANSI terminal state machine.
 * Handles CSI sequences for cursor movement, SGR attributes/colors,
 * erase operations, scroll regions, insert/delete lines/characters,
 * and partial escape sequence handling across chunk boundaries.
 */

#include "terminal.h"
#include <stdlib.h>
#include <string.h>

/* ================================================================
 * Color Palette
 * ================================================================ */

static const uint8_t pal16[16][3] = {
    {  0,   0,   0}, /* 0  Black        */
    {170,   0,   0}, /* 1  Red          */
    {  0, 170,   0}, /* 2  Green        */
    {170, 170,   0}, /* 3  Yellow       */
    {  0,   0, 170}, /* 4  Blue         */
    {170,   0, 170}, /* 5  Magenta      */
    {  0, 170, 170}, /* 6  Cyan         */
    {170, 170, 170}, /* 7  White        */
    { 85,  85,  85}, /* 8  Bright Black */
    {255,  85,  85}, /* 9  Bright Red   */
    { 85, 255,  85}, /* 10 Bright Green */
    {255, 255,  85}, /* 11 Bright Yellow*/
    { 85,  85, 255}, /* 12 Bright Blue  */
    {255,  85, 255}, /* 13 Bright Magenta*/
    { 85, 255, 255}, /* 14 Bright Cyan  */
    {255, 255, 255}, /* 15 Bright White */
};

static void idx_to_rgb(int idx, uint8_t *r, uint8_t *g, uint8_t *b)
{
    if (idx < 0) idx = 0;
    if (idx > 255) idx = 255;

    if (idx < 16) {
        *r = pal16[idx][0];
        *g = pal16[idx][1];
        *b = pal16[idx][2];
    } else if (idx < 232) {
        int c  = idx - 16;
        int ri = c / 36;
        int gi = (c / 6) % 6;
        int bi = c % 6;
        *r = ri ? (uint8_t)(55 + 40 * ri) : 0;
        *g = gi ? (uint8_t)(55 + 40 * gi) : 0;
        *b = bi ? (uint8_t)(55 + 40 * bi) : 0;
    } else {
        uint8_t v = (uint8_t)(8 + (idx - 232) * 10);
        *r = *g = *b = v;
    }
}

/* ================================================================
 * Parser State Machine
 * ================================================================ */

typedef enum {
    PS_GROUND,
    PS_ESC,
    PS_ESC_INTER,
    PS_CSI,
    PS_OSC,
    PS_OSC_ESC,
} PState;

#define MAX_CSI_PARAMS 16

struct Terminal {
    int w, h;
    Cell *cells;

    /* Cursor position (0-indexed) */
    int cx, cy;

    /* Current pen (graphic rendition state) */
    uint8_t fg_r, fg_g, fg_b;
    uint8_t bg_r, bg_g, bg_b;
    uint32_t attrs;

    /* Parser */
    PState ps;
    int params[MAX_CSI_PARAMS];
    int np;           /* number of collected params */
    int cpv;          /* current param value being accumulated */
    int pseen;        /* have we seen any digit or ';'? */
    int priv;         /* CSI private marker '?' */

    /* Scroll region (0-indexed, inclusive) */
    int stop, sbot;

    /* Saved cursor (DECSC / ESC 7) */
    int sv_cx, sv_cy;
    uint8_t sv_fg_r, sv_fg_g, sv_fg_b;
    uint8_t sv_bg_r, sv_bg_g, sv_bg_b;
    uint32_t sv_attrs;

    /* Pending autowrap */
    int wnext;
};

/* ================================================================
 * Low-level helpers
 * ================================================================ */

static inline Cell *get_cell(Terminal *t, int x, int y)
{
    return &t->cells[y * t->w + x];
}

/* Clear a single cell using current pen background */
static void clear_cell(Terminal *t, int x, int y)
{
    Cell *c = get_cell(t, x, y);
    c->codepoint = 0;
    c->fg_r = DEFAULT_FG_R;
    c->fg_g = DEFAULT_FG_G;
    c->fg_b = DEFAULT_FG_B;
    c->bg_r = t->bg_r;
    c->bg_g = t->bg_g;
    c->bg_b = t->bg_b;
    c->attrs = 0;
}

/* Clear an entire row */
static void clear_row(Terminal *t, int y)
{
    for (int x = 0; x < t->w; x++)
        clear_cell(t, x, y);
}

static void clamp_cursor(Terminal *t)
{
    if (t->cx < 0)    t->cx = 0;
    if (t->cx >= t->w) t->cx = t->w - 1;
    if (t->cy < 0)    t->cy = 0;
    if (t->cy >= t->h) t->cy = t->h - 1;
}

static void reset_pen(Terminal *t)
{
    t->fg_r = DEFAULT_FG_R; t->fg_g = DEFAULT_FG_G; t->fg_b = DEFAULT_FG_B;
    t->bg_r = DEFAULT_BG_R; t->bg_g = DEFAULT_BG_G; t->bg_b = DEFAULT_BG_B;
    t->attrs = 0;
}

/* ================================================================
 * Cursor save / restore
 * ================================================================ */

static void save_cursor(Terminal *t)
{
    t->sv_cx = t->cx;   t->sv_cy = t->cy;
    t->sv_fg_r = t->fg_r; t->sv_fg_g = t->fg_g; t->sv_fg_b = t->fg_b;
    t->sv_bg_r = t->bg_r; t->sv_bg_g = t->bg_g; t->sv_bg_b = t->bg_b;
    t->sv_attrs = t->attrs;
}

static void restore_cursor(Terminal *t)
{
    t->cx = t->sv_cx;   t->cy = t->sv_cy;
    t->fg_r = t->sv_fg_r; t->fg_g = t->sv_fg_g; t->fg_b = t->sv_fg_b;
    t->bg_r = t->sv_bg_r; t->bg_g = t->sv_bg_g; t->bg_b = t->sv_bg_b;
    t->attrs = t->sv_attrs;
    t->wnext = 0;
    clamp_cursor(t);
}

/* ================================================================
 * Scrolling
 * ================================================================ */

static void scroll_up_n(Terminal *t, int n)
{
    for (int i = 0; i < n; i++) {
        if (t->stop >= t->sbot) break;
        memmove(&t->cells[t->stop * t->w],
                &t->cells[(t->stop + 1) * t->w],
                (size_t)(t->sbot - t->stop) * (size_t)t->w * sizeof(Cell));
        clear_row(t, t->sbot);
    }
}

static void scroll_down_n(Terminal *t, int n)
{
    for (int i = 0; i < n; i++) {
        if (t->stop >= t->sbot) break;
        memmove(&t->cells[(t->stop + 1) * t->w],
                &t->cells[t->stop * t->w],
                (size_t)(t->sbot - t->stop) * (size_t)t->w * sizeof(Cell));
        clear_row(t, t->stop);
    }
}

/* ================================================================
 * Line feed / reverse index
 * ================================================================ */

static void do_linefeed(Terminal *t)
{
    if (t->cy == t->sbot) {
        scroll_up_n(t, 1);
    } else if (t->cy < t->h - 1) {
        t->cy++;
    }
    t->wnext = 0;
}

static void do_reverse_index(Terminal *t)
{
    if (t->cy == t->stop) {
        scroll_down_n(t, 1);
    } else if (t->cy > 0) {
        t->cy--;
    }
    t->wnext = 0;
}

static void do_next_line(Terminal *t)
{
    t->cx = 0;
    do_linefeed(t);
}

/* ================================================================
 * Character output
 * ================================================================ */

static void put_char(Terminal *t, uint32_t codepoint)
{
    if (t->wnext) {
        t->cx = 0;
        do_linefeed(t);
        t->wnext = 0;
    }

    if (t->cx >= 0 && t->cx < t->w && t->cy >= 0 && t->cy < t->h) {
        Cell *c = get_cell(t, t->cx, t->cy);
        c->codepoint = codepoint;
        c->fg_r = t->fg_r; c->fg_g = t->fg_g; c->fg_b = t->fg_b;
        c->bg_r = t->bg_r; c->bg_g = t->bg_g; c->bg_b = t->bg_b;
        c->attrs = t->attrs;
    }

    if (t->cx < t->w - 1) {
        t->cx++;
    } else {
        t->wnext = 1;
    }
}

/* ================================================================
 * Erase operations
 * ================================================================ */

static void erase_in_line(Terminal *t, int mode)
{
    switch (mode) {
    case 0: /* cursor to end */
        for (int x = t->cx; x < t->w; x++) clear_cell(t, x, t->cy);
        break;
    case 1: /* beginning to cursor (inclusive) */
        for (int x = 0; x <= t->cx && x < t->w; x++) clear_cell(t, x, t->cy);
        break;
    case 2: /* entire line */
        clear_row(t, t->cy);
        break;
    }
}

static void erase_in_display(Terminal *t, int mode)
{
    switch (mode) {
    case 0: /* cursor to end of display */
        for (int x = t->cx; x < t->w; x++) clear_cell(t, x, t->cy);
        for (int y = t->cy + 1; y < t->h; y++) clear_row(t, y);
        break;
    case 1: /* beginning to cursor (inclusive) */
        for (int y = 0; y < t->cy; y++) clear_row(t, y);
        for (int x = 0; x <= t->cx && x < t->w; x++) clear_cell(t, x, t->cy);
        break;
    case 2: /* entire display */
    case 3:
        for (int y = 0; y < t->h; y++) clear_row(t, y);
        break;
    }
}

/* ================================================================
 * Insert / Delete lines
 * ================================================================ */

static void insert_lines(Terminal *t, int n)
{
    if (t->cy < t->stop || t->cy > t->sbot) return;
    int avail = t->sbot - t->cy + 1;
    if (n > avail) n = avail;
    int move = avail - n;
    if (move > 0) {
        memmove(&t->cells[(t->cy + n) * t->w],
                &t->cells[t->cy * t->w],
                (size_t)move * (size_t)t->w * sizeof(Cell));
    }
    for (int i = 0; i < n; i++) clear_row(t, t->cy + i);
}

static void delete_lines(Terminal *t, int n)
{
    if (t->cy < t->stop || t->cy > t->sbot) return;
    int avail = t->sbot - t->cy + 1;
    if (n > avail) n = avail;
    int move = avail - n;
    if (move > 0) {
        memmove(&t->cells[t->cy * t->w],
                &t->cells[(t->cy + n) * t->w],
                (size_t)move * (size_t)t->w * sizeof(Cell));
    }
    for (int i = 0; i < n; i++) clear_row(t, t->sbot - i);
}

/* ================================================================
 * Insert / Delete / Erase characters
 * ================================================================ */

static void insert_chars(Terminal *t, int n)
{
    int avail = t->w - t->cx;
    if (n > avail) n = avail;
    int move = avail - n;
    if (move > 0) {
        memmove(get_cell(t, t->cx + n, t->cy),
                get_cell(t, t->cx, t->cy),
                (size_t)move * sizeof(Cell));
    }
    for (int i = 0; i < n; i++) clear_cell(t, t->cx + i, t->cy);
}

static void delete_chars(Terminal *t, int n)
{
    int avail = t->w - t->cx;
    if (n > avail) n = avail;
    int move = avail - n;
    if (move > 0) {
        memmove(get_cell(t, t->cx, t->cy),
                get_cell(t, t->cx + n, t->cy),
                (size_t)move * sizeof(Cell));
    }
    for (int i = 0; i < n; i++) clear_cell(t, t->w - 1 - i, t->cy);
}

static void erase_chars(Terminal *t, int n)
{
    for (int i = 0; i < n && t->cx + i < t->w; i++)
        clear_cell(t, t->cx + i, t->cy);
}

/* ================================================================
 * SGR (Select Graphic Rendition)
 * ================================================================ */

static void handle_sgr(Terminal *t)
{
    if (t->np == 0) {
        reset_pen(t);
        return;
    }

    int i = 0;
    while (i < t->np) {
        int p = t->params[i];

        switch (p) {
        case 0: reset_pen(t); break;
        case 1: t->attrs |= ATTR_BOLD; break;
        case 2: t->attrs |= ATTR_DIM; break;
        case 3: t->attrs |= ATTR_ITALIC; break;
        case 4: t->attrs |= ATTR_UNDERLINE; break;
        case 5: t->attrs |= ATTR_BLINK; break;
        case 7: t->attrs |= ATTR_REVERSE; break;
        case 8: t->attrs |= ATTR_INVISIBLE; break;
        case 9: t->attrs |= ATTR_STRIKETHROUGH; break;

        case 22: t->attrs &= ~(ATTR_BOLD | ATTR_DIM); break;
        case 23: t->attrs &= ~ATTR_ITALIC; break;
        case 24: t->attrs &= ~ATTR_UNDERLINE; break;
        case 25: t->attrs &= ~ATTR_BLINK; break;
        case 27: t->attrs &= ~ATTR_REVERSE; break;
        case 28: t->attrs &= ~ATTR_INVISIBLE; break;
        case 29: t->attrs &= ~ATTR_STRIKETHROUGH; break;

        /* Standard foreground colors */
        case 30: case 31: case 32: case 33:
        case 34: case 35: case 36: case 37:
            idx_to_rgb(p - 30, &t->fg_r, &t->fg_g, &t->fg_b);
            break;

        case 38: /* Extended foreground color */
            if (i + 1 < t->np && t->params[i + 1] == 5 && i + 2 < t->np) {
                idx_to_rgb(t->params[i + 2], &t->fg_r, &t->fg_g, &t->fg_b);
                i += 2;
            } else if (i + 1 < t->np && t->params[i + 1] == 2 && i + 4 < t->np) {
                t->fg_r = (uint8_t)t->params[i + 2];
                t->fg_g = (uint8_t)t->params[i + 3];
                t->fg_b = (uint8_t)t->params[i + 4];
                i += 4;
            }
            break;

        case 39: /* Default foreground */
            t->fg_r = DEFAULT_FG_R;
            t->fg_g = DEFAULT_FG_G;
            t->fg_b = DEFAULT_FG_B;
            break;

        /* Standard background colors */
        case 40: case 41: case 42: case 43:
        case 44: case 45: case 46: case 47:
            idx_to_rgb(p - 40, &t->bg_r, &t->bg_g, &t->bg_b);
            break;

        case 48: /* Extended background color */
            if (i + 1 < t->np && t->params[i + 1] == 5 && i + 2 < t->np) {
                idx_to_rgb(t->params[i + 2], &t->bg_r, &t->bg_g, &t->bg_b);
                i += 2;
            } else if (i + 1 < t->np && t->params[i + 1] == 2 && i + 4 < t->np) {
                t->bg_r = (uint8_t)t->params[i + 2];
                t->bg_g = (uint8_t)t->params[i + 3];
                t->bg_b = (uint8_t)t->params[i + 4];
                i += 4;
            }
            break;

        case 49: /* Default background */
            t->bg_r = DEFAULT_BG_R;
            t->bg_g = DEFAULT_BG_G;
            t->bg_b = DEFAULT_BG_B;
            break;

        /* Bright foreground colors */
        case 90: case 91: case 92: case 93:
        case 94: case 95: case 96: case 97:
            idx_to_rgb(p - 90 + 8, &t->fg_r, &t->fg_g, &t->fg_b);
            break;

        /* Bright background colors */
        case 100: case 101: case 102: case 103:
        case 104: case 105: case 106: case 107:
            idx_to_rgb(p - 100 + 8, &t->bg_r, &t->bg_g, &t->bg_b);
            break;

        default:
            break;
        }

        i++;
    }
}

/* ================================================================
 * CSI command dispatch
 * ================================================================ */

static void dispatch_csi(Terminal *t, char cmd)
{
    int p0 = t->np > 0 ? t->params[0] : 0;
    int p1 = t->np > 1 ? t->params[1] : 0;
    int n;

    switch (cmd) {
    case 'A': /* CUU - Cursor Up */
        n = p0 ? p0 : 1;
        t->cy -= n;
        if (t->cy < 0) t->cy = 0;
        t->wnext = 0;
        break;

    case 'B': /* CUD - Cursor Down */
        n = p0 ? p0 : 1;
        t->cy += n;
        if (t->cy >= t->h) t->cy = t->h - 1;
        t->wnext = 0;
        break;

    case 'C': /* CUF - Cursor Forward */
        n = p0 ? p0 : 1;
        t->cx += n;
        if (t->cx >= t->w) t->cx = t->w - 1;
        t->wnext = 0;
        break;

    case 'D': /* CUB - Cursor Back */
        n = p0 ? p0 : 1;
        t->cx -= n;
        if (t->cx < 0) t->cx = 0;
        t->wnext = 0;
        break;

    case 'E': /* CNL - Cursor Next Line */
        n = p0 ? p0 : 1;
        t->cx = 0;
        t->cy += n;
        if (t->cy >= t->h) t->cy = t->h - 1;
        t->wnext = 0;
        break;

    case 'F': /* CPL - Cursor Previous Line */
        n = p0 ? p0 : 1;
        t->cx = 0;
        t->cy -= n;
        if (t->cy < 0) t->cy = 0;
        t->wnext = 0;
        break;

    case 'G': /* CHA - Cursor Horizontal Absolute */
        t->cx = (p0 ? p0 : 1) - 1;
        clamp_cursor(t);
        t->wnext = 0;
        break;

    case 'H': /* CUP - Cursor Position */
    case 'f': /* HVP - Horizontal and Vertical Position */
        t->cy = (p0 ? p0 : 1) - 1;
        t->cx = (p1 ? p1 : 1) - 1;
        clamp_cursor(t);
        t->wnext = 0;
        break;

    case 'J': /* ED - Erase in Display */
        erase_in_display(t, p0);
        break;

    case 'K': /* EL - Erase in Line */
        erase_in_line(t, p0);
        break;

    case 'L': /* IL - Insert Lines */
        insert_lines(t, p0 ? p0 : 1);
        break;

    case 'M': /* DL - Delete Lines */
        delete_lines(t, p0 ? p0 : 1);
        break;

    case 'P': /* DCH - Delete Characters */
        delete_chars(t, p0 ? p0 : 1);
        break;

    case 'S': /* SU - Scroll Up */
        scroll_up_n(t, p0 ? p0 : 1);
        break;

    case 'T': /* SD - Scroll Down */
        scroll_down_n(t, p0 ? p0 : 1);
        break;

    case 'X': /* ECH - Erase Characters */
        erase_chars(t, p0 ? p0 : 1);
        break;

    case '@': /* ICH - Insert Characters */
        insert_chars(t, p0 ? p0 : 1);
        break;

    case 'd': /* VPA - Vertical Position Absolute */
        t->cy = (p0 ? p0 : 1) - 1;
        clamp_cursor(t);
        t->wnext = 0;
        break;

    case 'm': /* SGR - Select Graphic Rendition */
        handle_sgr(t);
        break;

    case 'r': /* DECSTBM - Set Top and Bottom Margins */
    {
        int top = p0, bot = p1;
        if (top == 0 && bot == 0) {
            t->stop = 0;
            t->sbot = t->h - 1;
        } else {
            t->stop = (top ? top : 1) - 1;
            t->sbot = (bot ? bot : t->h) - 1;
            if (t->stop >= t->h) t->stop = t->h - 1;
            if (t->sbot >= t->h) t->sbot = t->h - 1;
            if (t->stop > t->sbot) {
                int tmp = t->stop;
                t->stop = t->sbot;
                t->sbot = tmp;
            }
        }
        /* DECSTBM moves cursor to home */
        t->cx = 0;
        t->cy = 0;
        t->wnext = 0;
        break;
    }

    case 's': /* SCP - Save Cursor Position (ANSI) */
        save_cursor(t);
        break;

    case 'u': /* RCP - Restore Cursor Position (ANSI) */
        restore_cursor(t);
        break;

    default:
        break;
    }
}

/* ================================================================
 * Terminal reset
 * ================================================================ */

static void do_reset(Terminal *t)
{
    t->cx = 0;
    t->cy = 0;
    reset_pen(t);
    t->stop = 0;
    t->sbot = t->h - 1;
    t->wnext = 0;
    t->ps = PS_GROUND;
    t->sv_cx = 0; t->sv_cy = 0;
    t->sv_fg_r = DEFAULT_FG_R; t->sv_fg_g = DEFAULT_FG_G; t->sv_fg_b = DEFAULT_FG_B;
    t->sv_bg_r = DEFAULT_BG_R; t->sv_bg_g = DEFAULT_BG_G; t->sv_bg_b = DEFAULT_BG_B;
    t->sv_attrs = 0;
    for (int y = 0; y < t->h; y++) clear_row(t, y);
}

/* ================================================================
 * CSI parser state reset
 * ================================================================ */

static void csi_reset(Terminal *t)
{
    t->np = 0;
    t->cpv = 0;
    t->pseen = 0;
    t->priv = 0;
}

/* ================================================================
 * Main byte processing
 * ================================================================ */

void terminal_process(Terminal *t, const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        uint8_t ch = data[i];

        switch (t->ps) {

        case PS_GROUND:
            if (ch == 0x1b) {
                t->ps = PS_ESC;
            } else if (ch >= 0x20 && ch < 0x7f) {
                put_char(t, (uint32_t)ch);
            } else if (ch == '\n') {
                do_linefeed(t);
            } else if (ch == '\r') {
                t->cx = 0;
                t->wnext = 0;
            } else if (ch == '\t') {
                t->cx = ((t->cx / 8) + 1) * 8;
                if (t->cx >= t->w) t->cx = t->w - 1;
                t->wnext = 0;
            } else if (ch == '\b') {
                if (t->cx > 0) t->cx--;
                t->wnext = 0;
            }
            /* Other control characters are silently ignored */
            break;

        case PS_ESC:
            switch (ch) {
            case '[':
                csi_reset(t);
                t->ps = PS_CSI;
                break;
            case ']':
                t->ps = PS_OSC;
                break;
            case '7':
                save_cursor(t);
                t->ps = PS_GROUND;
                break;
            case '8':
                restore_cursor(t);
                t->ps = PS_GROUND;
                break;
            case 'D':
                do_linefeed(t);
                t->ps = PS_GROUND;
                break;
            case 'E':
                do_next_line(t);
                t->ps = PS_GROUND;
                break;
            case 'M':
                do_reverse_index(t);
                t->ps = PS_GROUND;
                break;
            case 'c':
                do_reset(t);
                /* ps already set to PS_GROUND by do_reset */
                break;
            case '(':
            case ')':
            case '#':
                t->ps = PS_ESC_INTER;
                break;
            default:
                t->ps = PS_GROUND;
                break;
            }
            break;

        case PS_ESC_INTER:
            /* Consume exactly one byte after ESC ( / ) / # and return */
            t->ps = PS_GROUND;
            break;

        case PS_CSI:
            if (ch >= '0' && ch <= '9') {
                t->cpv = t->cpv * 10 + (ch - '0');
                t->pseen = 1;
            } else if (ch == ';') {
                if (t->np < MAX_CSI_PARAMS)
                    t->params[t->np++] = t->cpv;
                t->cpv = 0;
                t->pseen = 1;
            } else if (ch == '?') {
                t->priv = 1;
            } else if (ch >= 0x40 && ch <= 0x7e) {
                /* Final command byte */
                if (t->pseen && t->np < MAX_CSI_PARAMS)
                    t->params[t->np++] = t->cpv;
                if (!t->priv)
                    dispatch_csi(t, (char)ch);
                t->ps = PS_GROUND;
            } else if (ch >= 0x20 && ch <= 0x2f) {
                /* Intermediate byte - silently consumed */
            } else {
                /* Invalid byte in CSI - abort */
                t->ps = PS_GROUND;
            }
            break;

        case PS_OSC:
            if (ch == 0x07) {
                t->ps = PS_GROUND;
            } else if (ch == 0x1b) {
                t->ps = PS_OSC_ESC;
            }
            /* All other bytes consumed silently */
            break;

        case PS_OSC_ESC:
            if (ch == '\\') {
                t->ps = PS_GROUND;  /* String Terminator received */
            } else {
                t->ps = PS_OSC;     /* Not ST, continue OSC string */
            }
            break;
        }
    }
}

/* ================================================================
 * Public API
 * ================================================================ */

Terminal *terminal_create(int width, int height)
{
    Terminal *t = (Terminal *)calloc(1, sizeof(Terminal));
    if (!t) return NULL;

    t->w = width;
    t->h = height;
    t->cells = (Cell *)calloc((size_t)width * (size_t)height, sizeof(Cell));
    if (!t->cells) { free(t); return NULL; }

    /* Set default pen colors */
    t->fg_r = DEFAULT_FG_R; t->fg_g = DEFAULT_FG_G; t->fg_b = DEFAULT_FG_B;
    /* bg already zeroed by calloc, matches DEFAULT_BG */

    /* Full-screen scroll region */
    t->sbot = height - 1;

    /* Initialize saved cursor defaults */
    t->sv_fg_r = DEFAULT_FG_R; t->sv_fg_g = DEFAULT_FG_G; t->sv_fg_b = DEFAULT_FG_B;

    /* Initialize all cells with proper default colors */
    for (int y = 0; y < height; y++)
        clear_row(t, y);

    return t;
}

void terminal_destroy(Terminal *t)
{
    if (t) {
        free(t->cells);
        free(t);
    }
}

Cell terminal_get_cell(const Terminal *t, int x, int y)
{
    if (x >= 0 && x < t->w && y >= 0 && y < t->h)
        return t->cells[y * t->w + x];
    Cell empty;
    memset(&empty, 0, sizeof(empty));
    return empty;
}

int terminal_get_cursor_x(const Terminal *t) { return t->cx; }
int terminal_get_cursor_y(const Terminal *t) { return t->cy; }
