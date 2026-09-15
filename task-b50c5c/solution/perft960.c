/*
 * perft960.c - Chess & Chess960 (Fischer Random) perft calculator
 * Supports both standard chess (KQkq) and X-FEN/Shredder-FEN castling
 * notation (file letters A-H, a-h). Handles all Chess960 castling edge
 * cases including king-stays, rook-to-king-origin, and king-rook swap.
 *
 * Usage: ./perft "FEN_STRING" depth
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Piece types */
enum { EMPTY_SQ, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING };

/* Castling right bits */
#define CWK 1
#define CWQ 2
#define CBK 4
#define CBQ 8

/* Board state */
typedef struct {
    int sq[64];        /* positive = white, negative = black, abs = piece type */
    int side;          /* +1 white, -1 black */
    int castle;        /* castling rights bitmask */
    int ep;            /* en passant target square, -1 if none */
    int king_sq[2];    /* king positions: [0]=white, [1]=black */
    int castle_rook[4]; /* initial rook squares: [0]=WK, [1]=WQ, [2]=BK, [3]=BQ */
} Board;

/* Move representation */
typedef struct {
    int from;
    int to;
    int captured;
    int promotion;     /* promoted piece type (signed), 0 if not promotion */
    int flags;         /* bit 0 = en passant, bit 1 = castling */
    int prev_castle;   /* saved for unmake */
    int prev_ep;
    int rook_from;     /* for castling: rook's original square */
} Move;

/* Extended perft statistics */
typedef struct {
    long long nodes;
    long long captures;
    long long ep;
    long long castles;
    long long promotions;
    long long checks;
    long long checkmates;
} Stats;

/* Utility macros */
#define RANK(s)       ((s) >> 3)
#define FILEOF(s)     ((s) & 7)
#define SQ(r,f)       (((r) << 3) | (f))
#define ONBOARD(r,f)  ((unsigned)(r) < 8 && (unsigned)(f) < 8)
#define PTYPE(p)      ((p) < 0 ? -(p) : (p))
#define IS_WHITE(p)   ((p) > 0)
#define IS_BLACK(p)   ((p) < 0)
#define IS_ALLY(p,s)  ((s) > 0 ? IS_WHITE(p) : IS_BLACK(p))
#define IS_ENEMY(p,s) ((s) > 0 ? IS_BLACK(p) : IS_WHITE(p))

/* Direction tables */
static const int knight_dir[8][2] = {
    {-2,-1},{-2,1},{-1,-2},{-1,2},{1,-2},{1,2},{2,-1},{2,1}
};
static const int king_dir[8][2] = {
    {-1,-1},{-1,0},{-1,1},{0,-1},{0,1},{1,-1},{1,0},{1,1}
};
static const int slide_dir[8][2] = {
    {-1,-1},{-1,1},{1,-1},{1,1},   /* 0-3: diagonals (bishop) */
    {-1,0},{0,-1},{0,1},{1,0}      /* 4-7: orthogonals (rook) */
};

/* ================================================================
 * FEN Parser (supports X-FEN / Shredder-FEN for Chess960)
 * ================================================================ */
void parse_fen(Board *b, const char *fen) {
    memset(b, 0, sizeof(*b));
    b->ep = -1;
    b->castle_rook[0] = b->castle_rook[1] = -1;
    b->castle_rook[2] = b->castle_rook[3] = -1;

    int pos = 56;  /* start at a8 */
    int i = 0;

    /* Piece placement */
    while (fen[i] && fen[i] != ' ') {
        if (fen[i] == '/') {
            pos -= 16;
        } else if (fen[i] >= '1' && fen[i] <= '8') {
            pos += fen[i] - '0';
        } else {
            int p = 0;
            switch (fen[i]) {
                case 'P': p =  PAWN;   break; case 'p': p = -PAWN;   break;
                case 'N': p =  KNIGHT; break; case 'n': p = -KNIGHT; break;
                case 'B': p =  BISHOP; break; case 'b': p = -BISHOP; break;
                case 'R': p =  ROOK;   break; case 'r': p = -ROOK;   break;
                case 'Q': p =  QUEEN;  break; case 'q': p = -QUEEN;  break;
                case 'K': p =  KING; b->king_sq[0] = pos; break;
                case 'k': p = -KING; b->king_sq[1] = pos; break;
            }
            b->sq[pos++] = p;
        }
        i++;
    }

    /* Side to move */
    if (fen[i] == ' ') i++;
    b->side = (fen[i] == 'w') ? 1 : -1;
    i++;

    /* Castling availability: supports KQkq and file letters A-H, a-h */
    if (fen[i] == ' ') i++;
    while (fen[i] && fen[i] != ' ') {
        if (fen[i] == 'K') {
            /* Outermost white rook to the right of king */
            b->castle |= CWK;
            for (int f = 7; f > FILEOF(b->king_sq[0]); f--) {
                if (b->sq[SQ(0, f)] == ROOK) {
                    b->castle_rook[0] = SQ(0, f);
                    break;
                }
            }
        } else if (fen[i] == 'Q') {
            /* Outermost white rook to the left of king */
            b->castle |= CWQ;
            for (int f = 0; f < FILEOF(b->king_sq[0]); f++) {
                if (b->sq[SQ(0, f)] == ROOK) {
                    b->castle_rook[1] = SQ(0, f);
                    break;
                }
            }
        } else if (fen[i] == 'k') {
            /* Outermost black rook to the right of king */
            b->castle |= CBK;
            for (int f = 7; f > FILEOF(b->king_sq[1]); f--) {
                if (b->sq[SQ(7, f)] == -ROOK) {
                    b->castle_rook[2] = SQ(7, f);
                    break;
                }
            }
        } else if (fen[i] == 'q') {
            /* Outermost black rook to the left of king */
            b->castle |= CBQ;
            for (int f = 0; f < FILEOF(b->king_sq[1]); f++) {
                if (b->sq[SQ(7, f)] == -ROOK) {
                    b->castle_rook[3] = SQ(7, f);
                    break;
                }
            }
        } else if (fen[i] >= 'A' && fen[i] <= 'H') {
            /* X-FEN: explicit white rook file */
            int file = fen[i] - 'A';
            if (file > FILEOF(b->king_sq[0])) {
                b->castle |= CWK;
                b->castle_rook[0] = SQ(0, file);
            } else {
                b->castle |= CWQ;
                b->castle_rook[1] = SQ(0, file);
            }
        } else if (fen[i] >= 'a' && fen[i] <= 'h') {
            /* X-FEN: explicit black rook file */
            int file = fen[i] - 'a';
            if (file > FILEOF(b->king_sq[1])) {
                b->castle |= CBK;
                b->castle_rook[2] = SQ(7, file);
            } else {
                b->castle |= CBQ;
                b->castle_rook[3] = SQ(7, file);
            }
        }
        i++;
    }

    /* En passant target square */
    if (fen[i] == ' ') i++;
    if (fen[i] && fen[i] >= 'a' && fen[i] <= 'h') {
        int f = fen[i] - 'a';
        int r = fen[i+1] - '1';
        b->ep = SQ(r, f);
    }
}

/* ================================================================
 * Attack Detection
 * ================================================================ */
int is_attacked(const Board *b, int sq, int by_side) {
    int r = RANK(sq), f = FILEOF(sq);
    int nr, nf, p, i;

    /* Knight attacks */
    for (i = 0; i < 8; i++) {
        nr = r + knight_dir[i][0];
        nf = f + knight_dir[i][1];
        if (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (PTYPE(p) == KNIGHT && IS_ALLY(p, by_side))
                return 1;
        }
    }

    /* King attacks */
    for (i = 0; i < 8; i++) {
        nr = r + king_dir[i][0];
        nf = f + king_dir[i][1];
        if (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (PTYPE(p) == KING && IS_ALLY(p, by_side))
                return 1;
        }
    }

    /* Pawn attacks */
    if (by_side > 0) {
        if (r > 0) {
            if (f > 0 && b->sq[SQ(r-1, f-1)] == PAWN) return 1;
            if (f < 7 && b->sq[SQ(r-1, f+1)] == PAWN) return 1;
        }
    } else {
        if (r < 7) {
            if (f > 0 && b->sq[SQ(r+1, f-1)] == -PAWN) return 1;
            if (f < 7 && b->sq[SQ(r+1, f+1)] == -PAWN) return 1;
        }
    }

    /* Diagonal sliding (bishop / queen) */
    for (i = 0; i < 4; i++) {
        nr = r + slide_dir[i][0];
        nf = f + slide_dir[i][1];
        while (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (p) {
                int t = PTYPE(p);
                if ((t == BISHOP || t == QUEEN) && IS_ALLY(p, by_side))
                    return 1;
                break;
            }
            nr += slide_dir[i][0];
            nf += slide_dir[i][1];
        }
    }

    /* Orthogonal sliding (rook / queen) */
    for (i = 4; i < 8; i++) {
        nr = r + slide_dir[i][0];
        nf = f + slide_dir[i][1];
        while (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (p) {
                int t = PTYPE(p);
                if ((t == ROOK || t == QUEEN) && IS_ALLY(p, by_side))
                    return 1;
                break;
            }
            nr += slide_dir[i][0];
            nf += slide_dir[i][1];
        }
    }

    return 0;
}

/* ================================================================
 * Move Generation (pseudo-legal)
 * ================================================================ */
#define MAXMOVES 256

typedef struct {
    Move moves[MAXMOVES];
    int count;
} MoveList;

static void push(MoveList *ml, int from, int to, int cap, int promo, int flags) {
    Move *m = &ml->moves[ml->count++];
    m->from = from;
    m->to = to;
    m->captured = cap;
    m->promotion = promo;
    m->flags = flags;
    m->rook_from = 0;
}

static void push_castle(MoveList *ml, int king_from, int king_to, int rook_from) {
    Move *m = &ml->moves[ml->count++];
    m->from = king_from;
    m->to = king_to;
    m->captured = 0;
    m->promotion = 0;
    m->flags = 2;
    m->rook_from = rook_from;
}

/* Try to generate a castling move. Returns 1 if legal, 0 otherwise. */
static int try_castle(const Board *b, MoveList *ml,
                      int king_sq, int king_to_f,
                      int rook_sq, int rook_to_f,
                      int opp_side) {
    int rank = RANK(king_sq);
    int king_from_f = FILEOF(king_sq);
    int rook_from_f = FILEOF(rook_sq);

    /* Compute the full span of squares that must be clear */
    int min_f = king_from_f, max_f = king_from_f;
    if (king_to_f  < min_f) min_f = king_to_f;
    if (king_to_f  > max_f) max_f = king_to_f;
    if (rook_from_f < min_f) min_f = rook_from_f;
    if (rook_from_f > max_f) max_f = rook_from_f;
    if (rook_to_f  < min_f) min_f = rook_to_f;
    if (rook_to_f  > max_f) max_f = rook_to_f;

    /* All squares in the span must be empty, except the castling king and rook */
    for (int ff = min_f; ff <= max_f; ff++) {
        int tsq = SQ(rank, ff);
        if (tsq == king_sq || tsq == rook_sq) continue;
        if (b->sq[tsq] != 0) return 0;
    }

    /* King must not start on, pass through, or end on an attacked square */
    if (king_from_f == king_to_f) {
        /* King doesn't move - only check current square */
        if (is_attacked(b, king_sq, opp_side)) return 0;
    } else {
        int step = (king_to_f > king_from_f) ? 1 : -1;
        for (int ff = king_from_f; ; ff += step) {
            if (is_attacked(b, SQ(rank, ff), opp_side)) return 0;
            if (ff == king_to_f) break;
        }
    }

    push_castle(ml, king_sq, SQ(rank, king_to_f), rook_sq);
    return 1;
}

void generate_moves(Board *b, MoveList *ml) {
    int s = b->side;
    ml->count = 0;

    for (int sq = 0; sq < 64; sq++) {
        int pc = b->sq[sq];
        if (!pc || !IS_ALLY(pc, s)) continue;

        int pt = PTYPE(pc);
        int r = RANK(sq), f = FILEOF(sq);

        switch (pt) {

        case PAWN: {
            int dir = (s > 0) ? 1 : -1;
            int start_r = (s > 0) ? 1 : 6;
            int promo_r = (s > 0) ? 7 : 0;
            int nr = r + dir;

            /* Single push */
            if (ONBOARD(nr, f) && b->sq[SQ(nr, f)] == 0) {
                if (nr == promo_r) {
                    push(ml, sq, SQ(nr,f), 0, QUEEN*s, 0);
                    push(ml, sq, SQ(nr,f), 0, ROOK*s, 0);
                    push(ml, sq, SQ(nr,f), 0, BISHOP*s, 0);
                    push(ml, sq, SQ(nr,f), 0, KNIGHT*s, 0);
                } else {
                    push(ml, sq, SQ(nr,f), 0, 0, 0);
                    /* Double push */
                    if (r == start_r && b->sq[SQ(r + 2*dir, f)] == 0)
                        push(ml, sq, SQ(r+2*dir, f), 0, 0, 0);
                }
            }

            /* Captures and en passant */
            for (int df = -1; df <= 1; df += 2) {
                int nf = f + df;
                if (!ONBOARD(nr, nf)) continue;

                int tgt = b->sq[SQ(nr, nf)];
                if (tgt && IS_ENEMY(tgt, s)) {
                    if (nr == promo_r) {
                        push(ml, sq, SQ(nr,nf), tgt, QUEEN*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, ROOK*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, BISHOP*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, KNIGHT*s, 0);
                    } else {
                        push(ml, sq, SQ(nr,nf), tgt, 0, 0);
                    }
                }

                /* En passant capture */
                if (b->ep == SQ(nr, nf)) {
                    int cap_sq = SQ(r, nf);
                    push(ml, sq, SQ(nr,nf), b->sq[cap_sq], 0, 1);
                }
            }
            break;
        }

        case KNIGHT: {
            for (int i = 0; i < 8; i++) {
                int nr = r + knight_dir[i][0];
                int nf = f + knight_dir[i][1];
                if (!ONBOARD(nr, nf)) continue;
                int tgt = b->sq[SQ(nr, nf)];
                if (!tgt || IS_ENEMY(tgt, s))
                    push(ml, sq, SQ(nr,nf), tgt, 0, 0);
            }
            break;
        }

        case BISHOP: case ROOK: case QUEEN: {
            int sd = (pt == ROOK)   ? 4 : 0;
            int ed = (pt == BISHOP) ? 4 : 8;

            for (int d = sd; d < ed; d++) {
                int nr = r + slide_dir[d][0];
                int nf = f + slide_dir[d][1];
                while (ONBOARD(nr, nf)) {
                    int tgt = b->sq[SQ(nr, nf)];
                    if (!tgt) {
                        push(ml, sq, SQ(nr,nf), 0, 0, 0);
                    } else {
                        if (IS_ENEMY(tgt, s))
                            push(ml, sq, SQ(nr,nf), tgt, 0, 0);
                        break;
                    }
                    nr += slide_dir[d][0];
                    nf += slide_dir[d][1];
                }
            }
            break;
        }

        case KING: {
            /* Normal king moves */
            for (int i = 0; i < 8; i++) {
                int nr = r + king_dir[i][0];
                int nf = f + king_dir[i][1];
                if (!ONBOARD(nr, nf)) continue;
                int tgt = b->sq[SQ(nr, nf)];
                if (!tgt || IS_ENEMY(tgt, s))
                    push(ml, sq, SQ(nr,nf), tgt, 0, 0);
            }

            /* Chess960 generalized castling */
            {
                int opp = -s;
                int ks_bit = (s > 0) ? CWK : CBK;
                int ks_idx = (s > 0) ? 0 : 2;
                int qs_bit = (s > 0) ? CWQ : CBQ;
                int qs_idx = (s > 0) ? 1 : 3;

                /* Kingside: king -> g-file, rook -> f-file */
                if (b->castle & ks_bit)
                    try_castle(b, ml, sq, 6, b->castle_rook[ks_idx], 5, opp);

                /* Queenside: king -> c-file, rook -> d-file */
                if (b->castle & qs_bit)
                    try_castle(b, ml, sq, 2, b->castle_rook[qs_idx], 3, opp);
            }
            break;
        }

        } /* end switch */
    }
}

/* ================================================================
 * Make / Unmake Move
 * ================================================================ */
void make_move(Board *b, Move *m) {
    m->prev_castle = b->castle;
    m->prev_ep = b->ep;

    int pc = b->sq[m->from];
    int pt = PTYPE(pc);

    if (m->flags & 2) {
        /* Castling: handle as atomic operation to cover all Chess960 edge cases.
         * Clear both origin squares, then place both pieces on destinations.
         * This correctly handles: king-stays, rook-to-king-origin, king-rook swap. */
        int rook_sq = m->rook_from;
        int rook_pc = b->sq[rook_sq];
        int rank = RANK(m->from);
        int king_to_f = FILEOF(m->to);
        int rook_to_f = (king_to_f == 6) ? 5 : 3;

        /* Clear both source squares */
        b->sq[m->from] = 0;
        b->sq[rook_sq] = 0;

        /* Place on destinations */
        b->sq[m->to] = pc;
        b->sq[SQ(rank, rook_to_f)] = rook_pc;

        /* Update king position */
        b->king_sq[b->side > 0 ? 0 : 1] = m->to;

        /* Revoke all castling rights for the moving side */
        if (b->side > 0) b->castle &= ~(CWK | CWQ);
        else              b->castle &= ~(CBK | CBQ);

        b->ep = -1;
        b->side = -b->side;
        return;
    }

    /* En passant: remove the captured pawn */
    if (m->flags & 1) {
        int cap_sq = SQ(RANK(m->from), FILEOF(m->to));
        b->sq[cap_sq] = 0;
    }

    /* Place piece on destination (promotion replaces piece type) */
    b->sq[m->to] = m->promotion ? m->promotion : pc;
    b->sq[m->from] = 0;

    /* Update king position */
    if (pt == KING)
        b->king_sq[b->side > 0 ? 0 : 1] = m->to;

    /* Revoke castling rights when king moves */
    if (pt == KING) {
        if (b->side > 0) b->castle &= ~(CWK | CWQ);
        else              b->castle &= ~(CBK | CBQ);
    }

    /* Revoke castling rights when a rook moves from its initial square */
    if (pt == ROOK) {
        if (m->from == b->castle_rook[0]) b->castle &= ~CWK;
        if (m->from == b->castle_rook[1]) b->castle &= ~CWQ;
        if (m->from == b->castle_rook[2]) b->castle &= ~CBK;
        if (m->from == b->castle_rook[3]) b->castle &= ~CBQ;
    }

    /* Revoke castling rights when a rook is captured on its initial square */
    if (m->captured) {
        if (m->to == b->castle_rook[0]) b->castle &= ~CWK;
        if (m->to == b->castle_rook[1]) b->castle &= ~CWQ;
        if (m->to == b->castle_rook[2]) b->castle &= ~CBK;
        if (m->to == b->castle_rook[3]) b->castle &= ~CBQ;
    }

    /* Update en passant square */
    b->ep = -1;
    if (pt == PAWN) {
        int dr = RANK(m->to) - RANK(m->from);
        if (dr == 2 || dr == -2)
            b->ep = SQ((RANK(m->from) + RANK(m->to)) / 2, FILEOF(m->from));
    }

    b->side = -b->side;
}

void unmake_move(Board *b, Move *m) {
    b->side = -b->side;
    b->castle = m->prev_castle;
    b->ep = m->prev_ep;

    if (m->flags & 2) {
        /* Unmake castling: reverse the atomic operation */
        int rank = RANK(m->from);
        int king_to_f = FILEOF(m->to);
        int rook_to_f = (king_to_f == 6) ? 5 : 3;

        int king_pc = b->sq[m->to];
        int rook_pc = b->sq[SQ(rank, rook_to_f)];

        /* Clear destination squares */
        b->sq[m->to] = 0;
        b->sq[SQ(rank, rook_to_f)] = 0;

        /* Restore original positions */
        b->sq[m->from] = king_pc;
        b->sq[m->rook_from] = rook_pc;

        /* Restore king position */
        b->king_sq[b->side > 0 ? 0 : 1] = m->from;
        return;
    }

    int pc = b->sq[m->to];
    if (m->promotion)
        pc = PAWN * b->side;

    b->sq[m->from] = pc;
    b->sq[m->to] = (m->flags & 1) ? 0 : m->captured;

    /* Restore en passant captured pawn */
    if (m->flags & 1) {
        int cap_sq = SQ(RANK(m->from), FILEOF(m->to));
        b->sq[cap_sq] = m->captured;
    }

    /* Restore king position */
    if (PTYPE(pc) == KING)
        b->king_sq[b->side > 0 ? 0 : 1] = m->from;
}

/* ================================================================
 * Perft with extended statistics
 * ================================================================ */
void perft(Board *b, int depth, Stats *st) {
    MoveList ml;
    generate_moves(b, &ml);

    for (int i = 0; i < ml.count; i++) {
        Move *m = &ml.moves[i];

        make_move(b, m);

        /* Legality: the side that just moved must not have its king in check */
        int mover_ki = (b->side < 0) ? 0 : 1;
        if (is_attacked(b, b->king_sq[mover_ki], b->side)) {
            unmake_move(b, m);
            continue;
        }

        if (depth == 1) {
            st->nodes++;
            if (m->captured)   st->captures++;
            if (m->flags & 1)  st->ep++;
            if (m->flags & 2)  st->castles++;
            if (m->promotion)  st->promotions++;

            /* Check and checkmate detection on the opponent */
            int opp_ki = (b->side > 0) ? 0 : 1;
            if (is_attacked(b, b->king_sq[opp_ki], -b->side)) {
                st->checks++;

                /* Checkmate: opponent has no legal moves */
                MoveList ml2;
                generate_moves(b, &ml2);
                int has_legal = 0;
                for (int j = 0; j < ml2.count; j++) {
                    make_move(b, &ml2.moves[j]);
                    int mk = (b->side < 0) ? 0 : 1;
                    if (!is_attacked(b, b->king_sq[mk], b->side)) {
                        has_legal = 1;
                        unmake_move(b, &ml2.moves[j]);
                        break;
                    }
                    unmake_move(b, &ml2.moves[j]);
                }
                if (!has_legal) st->checkmates++;
            }
        } else {
            perft(b, depth - 1, st);
        }

        unmake_move(b, m);
    }
}

/* ================================================================
 * Main
 * ================================================================ */
int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s \"FEN\" depth\n", argv[0]);
        return 1;
    }

    Board board;
    parse_fen(&board, argv[1]);
    int depth = atoi(argv[2]);

    Stats stats = {0, 0, 0, 0, 0, 0, 0};
    perft(&board, depth, &stats);

    printf("nodes: %lld\n", stats.nodes);
    printf("captures: %lld\n", stats.captures);
    printf("ep: %lld\n", stats.ep);
    printf("castles: %lld\n", stats.castles);
    printf("promotions: %lld\n", stats.promotions);
    printf("checks: %lld\n", stats.checks);
    printf("checkmates: %lld\n", stats.checkmates);

    return 0;
}
