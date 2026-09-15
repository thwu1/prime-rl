/*
 * perft.c - Chess move path enumerator with extended statistics
 * Computes perft (performance test) node counts and detailed move
 * category breakdowns for any position given as a FEN string.
 *
 * Usage: ./perft "FEN_STRING" depth
 *
 * Output: nodes, captures, ep, castles, promotions, checks, checkmates
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
 * FEN Parser
 * ================================================================ */
void parse_fen(Board *b, const char *fen) {
    memset(b, 0, sizeof(*b));
    b->ep = -1;

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

    /* Castling availability */
    if (fen[i] == ' ') i++;
    while (fen[i] && fen[i] != ' ') {
        switch (fen[i]) {
            case 'K': b->castle |= CWK; break;
            case 'Q': b->castle |= CWQ; break;
            case 'k': b->castle |= CBK; break;
            case 'q': b->castle |= CBQ; break;
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

            /* Castling (standard chess: king on e1/e8) */
            if (s > 0 && sq == SQ(0, 4)) {
                /* White kingside */
                if ((b->castle & CWK) && !b->sq[5] && !b->sq[6]
                    && !is_attacked(b, SQ(0,4), -1)
                    && !is_attacked(b, SQ(0,5), -1)
                    && !is_attacked(b, SQ(0,6), -1))
                    push(ml, sq, SQ(0,6), 0, 0, 2);
                /* White queenside */
                if ((b->castle & CWQ) && !b->sq[1] && !b->sq[2] && !b->sq[3]
                    && !is_attacked(b, SQ(0,4), -1)
                    && !is_attacked(b, SQ(0,3), -1)
                    && !is_attacked(b, SQ(0,2), -1))
                    push(ml, sq, SQ(0,2), 0, 0, 2);
            }
            if (s < 0 && sq == SQ(7, 4)) {
                /* Black kingside */
                if ((b->castle & CBK) && !b->sq[61] && !b->sq[62]
                    && !is_attacked(b, SQ(7,4), 1)
                    && !is_attacked(b, SQ(7,5), 1)
                    && !is_attacked(b, SQ(7,6), 1))
                    push(ml, sq, SQ(7,6), 0, 0, 2);
                /* Black queenside */
                if ((b->castle & CBQ) && !b->sq[57] && !b->sq[58] && !b->sq[59]
                    && !is_attacked(b, SQ(7,4), 1)
                    && !is_attacked(b, SQ(7,3), 1)
                    && !is_attacked(b, SQ(7,2), 1))
                    push(ml, sq, SQ(7,2), 0, 0, 2);
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

    /* En passant: remove the captured pawn */
    if (m->flags & 1) {
        int cap_sq = SQ(RANK(m->from), FILEOF(m->to));
        b->sq[cap_sq] = 0;
    }

    /* Place piece on destination (promotion replaces piece type) */
    b->sq[m->to] = m->promotion ? m->promotion : pc;
    b->sq[m->from] = 0;

    /* Castling: move the rook */
    if (m->flags & 2) {
        switch (m->to) {
            case  6: b->sq[5]  = b->sq[7];  b->sq[7]  = 0; break;
            case  2: b->sq[3]  = b->sq[0];  b->sq[0]  = 0; break;
            case 62: b->sq[61] = b->sq[63]; b->sq[63] = 0; break;
            case 58: b->sq[59] = b->sq[56]; b->sq[56] = 0; break;
        }
    }

    /* Update king position */
    if (pt == KING)
        b->king_sq[b->side > 0 ? 0 : 1] = m->to;

    /* Revoke castling rights when king or rook moves */
    if (pt == KING) {
        if (b->side > 0) b->castle &= ~(CWK | CWQ);
        else              b->castle &= ~(CBK | CBQ);
    }
    if (pt == ROOK) {
        if (m->from == SQ(0,0)) b->castle &= ~CWQ;
        if (m->from == SQ(0,7)) b->castle &= ~CWK;
        if (m->from == SQ(7,0)) b->castle &= ~CBQ;
        if (m->from == SQ(7,7)) b->castle &= ~CBK;
    }

    /* Revoke castling rights when a rook is captured on its home square */
    if (m->captured) {
        if (m->to == SQ(0,0)) b->castle &= ~CWQ;
        if (m->to == SQ(0,7)) b->castle &= ~CWK;
        if (m->to == SQ(7,0)) b->castle &= ~CBQ;
        if (m->to == SQ(7,7)) b->castle &= ~CBK;
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

    /* Undo castling rook move */
    if (m->flags & 2) {
        switch (m->to) {
            case  6: b->sq[7]  = b->sq[5];  b->sq[5]  = 0; break;
            case  2: b->sq[0]  = b->sq[3];  b->sq[3]  = 0; break;
            case 62: b->sq[63] = b->sq[61]; b->sq[61] = 0; break;
            case 58: b->sq[56] = b->sq[59]; b->sq[59] = 0; break;
        }
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

        /* Legality check */
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
