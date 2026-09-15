
#ifndef TERMINAL_H
#define TERMINAL_H

#include <stdint.h>
#include <stddef.h>

/*
 * VT/ANSI Terminal State Machine API
 *
 * Attribute flags for Cell.attrs
 */
#define ATTR_BOLD          (1u << 0)
#define ATTR_DIM           (1u << 1)
#define ATTR_ITALIC        (1u << 2)
#define ATTR_UNDERLINE     (1u << 3)
#define ATTR_BLINK         (1u << 4)
#define ATTR_REVERSE       (1u << 5)
#define ATTR_INVISIBLE     (1u << 6)
#define ATTR_STRIKETHROUGH (1u << 7)

/*
 * Default foreground/background colors.
 * These must be used when SGR 0/39/49 resets colors.
 */
#define DEFAULT_FG_R 170
#define DEFAULT_FG_G 170
#define DEFAULT_FG_B 170
#define DEFAULT_BG_R 0
#define DEFAULT_BG_G 0
#define DEFAULT_BG_B 0

/*
 * Standard 16-color palette (indices 0-15).
 * Used for SGR 30-37, 40-47, 90-97, 100-107 and for
 * 256-color mode indices 0-15 (via SGR 38;5;N / 48;5;N).
 *
 *  0: (  0,   0,   0)  Black         8: ( 85,  85,  85)  Bright Black
 *  1: (170,   0,   0)  Red           9: (255,  85,  85)  Bright Red
 *  2: (  0, 170,   0)  Green        10: ( 85, 255,  85)  Bright Green
 *  3: (170, 170,   0)  Yellow       11: (255, 255,  85)  Bright Yellow
 *  4: (  0,   0, 170)  Blue         12: ( 85,  85, 255)  Bright Blue
 *  5: (170,   0, 170)  Magenta      13: (255,  85, 255)  Bright Magenta
 *  6: (  0, 170, 170)  Cyan         14: ( 85, 255, 255)  Bright Cyan
 *  7: (170, 170, 170)  White        15: (255, 255, 255)  Bright White
 *
 * 256-color palette (indices 16-231): 6x6x6 color cube.
 *   Component value = (index == 0) ? 0 : 55 + 40 * index
 *   r_index = (N - 16) / 36
 *   g_index = ((N - 16) / 6) % 6
 *   b_index = (N - 16) % 6
 *
 * 256-color palette (indices 232-255): grayscale ramp.
 *   gray = 8 + (N - 232) * 10
 */

typedef struct {
    uint32_t codepoint;       /* Unicode codepoint; 0 = empty/unwritten */
    uint8_t  fg_r, fg_g, fg_b;
    uint8_t  bg_r, bg_g, bg_b;
    uint32_t attrs;           /* Bitmask of ATTR_* flags */
} Cell;

typedef struct Terminal Terminal;

/* Create a new terminal with given dimensions (width=columns, height=rows). */
Terminal *terminal_create(int width, int height);

/* Destroy a terminal and free all resources. */
void terminal_destroy(Terminal *term);

/*
 * Process a chunk of input bytes through the terminal state machine.
 * This function may be called repeatedly with successive chunks of a byte
 * stream. Escape sequences that span chunk boundaries must be handled
 * correctly via persistent parser state.
 */
void terminal_process(Terminal *term, const uint8_t *data, size_t len);

/* Retrieve the cell at grid position (x, y). Both are 0-indexed. */
Cell terminal_get_cell(const Terminal *term, int x, int y);

/* Get current cursor X position (0-indexed column). */
int terminal_get_cursor_x(const Terminal *term);

/* Get current cursor Y position (0-indexed row). */
int terminal_get_cursor_y(const Terminal *term);

#endif /* TERMINAL_H */
