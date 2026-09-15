/*
 * perft_fixed.c - Corrected chess move path enumerator
 *
 * Fixes applied:
 * 1. Generate all four promotion types (queen, rook, bishop, knight)
 * 2. Revoke castling rights when a rook is captured on its home square
 * 3. Verify king is not in check and does not pass through attacked
 *    square when castling
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

typedef struct {
    int sq[64];
    int side;
    int castle;
    int ep;
    int king_sq[2];
} Board;

typedef struct {
    int from;
    int to;
    int captured;
    int promotion;
    int flags;
    int prev_castle;
    int prev_ep;
} Move;

typedef struct {
    long long nodes;
    long long captures;
    long long ep;
    long long castles;
    long long promotions;
    long long checks;
    long long checkmates;
} Stats;

#define RANK(s)       ((s) >> 3)
#define FILEOF(s)     ((s) & 7)
#define SQ(r,f)       (((r) << 3) | (f))
#define ONBOARD(r,f)  ((unsigned)(r) < 8 && (unsigned)(f) < 8)
#define PTYPE(p)      ((p) < 0 ? -(p) : (p))
#define IS_WHITE(p)   ((p) > 0)
#define IS_BLACK(p)   ((p) < 0)
#define IS_ALLY(p,s)  ((s) > 0 ? IS_WHITE(p) : IS_BLACK(p))
#define IS_ENEMY(p,s) ((s) > 0 ? IS_BLACK(p) : IS_WHITE(p))

static const int knight_dir[8][2] = {
    {-2,-1},{-2,1},{-1,-2},{-1,2},{1,-2},{1,2},{2,-1},{2,1}
};
static const int king_dir[8][2] = {
    {-1,-1},{-1,0},{-1,1},{0,-1},{0,1},{1,-1},{1,0},{1,1}
};
static const int slide_dir[8][2] = {
    {-1,-1},{-1,1},{1,-1},{1,1},
    {-1,0},{0,-1},{0,1},{1,0}
};

/* ================================================================ */
void parse_fen(Board *b, const char *fen) {
    memset(b, 0, sizeof(*b));
    b->ep = -1;
    int pos = 56;
    int i = 0;
    while (fen[i] && fen[i] != ' ') {
        if (fen[i] == '/') { pos -= 16; }
        else if (fen[i] >= '1' && fen[i] <= '8') { pos += fen[i] - '0'; }
        else {
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
    if (fen[i] == ' ') i++;
    b->side = (fen[i] == 'w') ? 1 : -1;
    i++;
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
    if (fen[i] == ' ') i++;
    if (fen[i] && fen[i] >= 'a' && fen[i] <= 'h') {
        int f = fen[i] - 'a';
        int r = fen[i+1] - '1';
        b->ep = SQ(r, f);
    }
}

/* ================================================================ */
int is_attacked(const Board *b, int sq, int by_side) {
    int r = RANK(sq), f = FILEOF(sq);
    int nr, nf, p, i;

    for (i = 0; i < 8; i++) {
        nr = r + knight_dir[i][0]; nf = f + knight_dir[i][1];
        if (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (PTYPE(p) == KNIGHT && IS_ALLY(p, by_side)) return 1;
        }
    }
    for (i = 0; i < 8; i++) {
        nr = r + king_dir[i][0]; nf = f + king_dir[i][1];
        if (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (PTYPE(p) == KING && IS_ALLY(p, by_side)) return 1;
        }
    }
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
    for (i = 0; i < 4; i++) {
        nr = r + slide_dir[i][0]; nf = f + slide_dir[i][1];
        while (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (p) {
                int t = PTYPE(p);
                if ((t == BISHOP || t == QUEEN) && IS_ALLY(p, by_side)) return 1;
                break;
            }
            nr += slide_dir[i][0]; nf += slide_dir[i][1];
        }
    }
    for (i = 4; i < 8; i++) {
        nr = r + slide_dir[i][0]; nf = f + slide_dir[i][1];
        while (ONBOARD(nr, nf)) {
            p = b->sq[SQ(nr, nf)];
            if (p) {
                int t = PTYPE(p);
                if ((t == ROOK || t == QUEEN) && IS_ALLY(p, by_side)) return 1;
                break;
            }
            nr += slide_dir[i][0]; nf += slide_dir[i][1];
        }
    }
    return 0;
}

/* ================================================================ */
#define MAXMOVES 256
typedef struct { Move moves[MAXMOVES]; int count; } MoveList;

static void push(MoveList *ml, int from, int to, int cap, int promo, int flags) {
    Move *m = &ml->moves[ml->count++];
    m->from = from; m->to = to; m->captured = cap;
    m->promotion = promo; m->flags = flags;
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

            if (ONBOARD(nr, f) && b->sq[SQ(nr, f)] == 0) {
                if (nr == promo_r) {
                    /* FIX 1: generate all four promotion types */
                    push(ml, sq, SQ(nr,f), 0, QUEEN*s, 0);
                    push(ml, sq, SQ(nr,f), 0, ROOK*s, 0);
                    push(ml, sq, SQ(nr,f), 0, BISHOP*s, 0);
                    push(ml, sq, SQ(nr,f), 0, KNIGHT*s, 0);
                } else {
                    push(ml, sq, SQ(nr,f), 0, 0, 0);
                    if (r == start_r && b->sq[SQ(r + 2*dir, f)] == 0)
                        push(ml, sq, SQ(r+2*dir, f), 0, 0, 0);
                }
            }

            for (int df = -1; df <= 1; df += 2) {
                int nf = f + df;
                if (!ONBOARD(nr, nf)) continue;
                int tgt = b->sq[SQ(nr, nf)];
                if (tgt && IS_ENEMY(tgt, s)) {
                    if (nr == promo_r) {
                        /* FIX 1: generate all four promotion types */
                        push(ml, sq, SQ(nr,nf), tgt, QUEEN*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, ROOK*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, BISHOP*s, 0);
                        push(ml, sq, SQ(nr,nf), tgt, KNIGHT*s, 0);
                    } else {
                        push(ml, sq, SQ(nr,nf), tgt, 0, 0);
                    }
                }
                if (b->ep == SQ(nr, nf)) {
                    int cap_sq = SQ(r, nf);
                    push(ml, sq, SQ(nr,nf), b->sq[cap_sq], 0, 1);
                }
            }
            break;
        }

        case KNIGHT: {
            for (int i = 0; i < 8; i++) {
                int nr = r + knight_dir[i][0], nf = f + knight_dir[i][1];
                if (!ONBOARD(nr, nf)) continue;
                int tgt = b->sq[SQ(nr, nf)];
                if (!tgt || IS_ENEMY(tgt, s))
                    push(ml, sq, SQ(nr,nf), tgt, 0, 0);
            }
            break;
        }

        case BISHOP: case ROOK: case QUEEN: {
            int sd = (pt == ROOK) ? 4 : 0;
            int ed = (pt == BISHOP) ? 4 : 8;
            for (int d = sd; d < ed; d++) {
                int nr = r + slide_dir[d][0], nf = f + slide_dir[d][1];
                while (ONBOARD(nr, nf)) {
                    int tgt = b->sq[SQ(nr, nf)];
                    if (!tgt) {
                        push(ml, sq, SQ(nr,nf), 0, 0, 0);
                    } else {
                        if (IS_ENEMY(tgt, s))
                            push(ml, sq, SQ(nr,nf), tgt, 0, 0);
                        break;
                    }
                    nr += slide_dir[d][0]; nf += slide_dir[d][1];
                }
            }
            break;
        }

        case KING: {
            for (int i = 0; i < 8; i++) {
                int nr = r + king_dir[i][0], nf = f + king_dir[i][1];
                if (!ONBOARD(nr, nf)) continue;
                int tgt = b->sq[SQ(nr, nf)];
                if (!tgt || IS_ENEMY(tgt, s))
                    push(ml, sq, SQ(nr,nf), tgt, 0, 0);
            }

            /* FIX 3: castling checks king not in check + intermediate square safe */
            if (s > 0 && sq == SQ(0, 4) && !is_attacked(b, sq, -1)) {
                if ((b->castle & CWK) && !b->sq[5] && !b->sq[6]
                    && !is_attacked(b, 5, -1))
                    push(ml, sq, SQ(0,6), 0, 0, 2);
                if ((b->castle & CWQ) && !b->sq[1] && !b->sq[2] && !b->sq[3]
                    && !is_attacked(b, 3, -1))
                    push(ml, sq, SQ(0,2), 0, 0, 2);
            }
            if (s < 0 && sq == SQ(7, 4) && !is_attacked(b, sq, 1)) {
                if ((b->castle & CBK) && !b->sq[61] && !b->sq[62]
                    && !is_attacked(b, 61, 1))
                    push(ml, sq, SQ(7,6), 0, 0, 2);
                if ((b->castle & CBQ) && !b->sq[57] && !b->sq[58] && !b->sq[59]
                    && !is_attacked(b, 59, 1))
                    push(ml, sq, SQ(7,2), 0, 0, 2);
            }
            break;
        }

        }
    }
}

/* ================================================================ */
void make_move(Board *b, Move *m) {
    m->prev_castle = b->castle;
    m->prev_ep = b->ep;
    int pc = b->sq[m->from];
    int pt = PTYPE(pc);

    if (m->flags & 1) {
        int cap_sq = SQ(RANK(m->from), FILEOF(m->to));
        b->sq[cap_sq] = 0;
    }

    b->sq[m->to] = m->promotion ? m->promotion : pc;
    b->sq[m->from] = 0;

    if (m->flags & 2) {
        switch (m->to) {
            case  6: b->sq[5]  = b->sq[7];  b->sq[7]  = 0; break;
            case  2: b->sq[3]  = b->sq[0];  b->sq[0]  = 0; break;
            case 62: b->sq[61] = b->sq[63]; b->sq[63] = 0; break;
            case 58: b->sq[59] = b->sq[56]; b->sq[56] = 0; break;
        }
    }

    if (pt == KING)
        b->king_sq[b->side > 0 ? 0 : 1] = m->to;

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

    /* FIX 2: revoke castling rights when a rook is captured */
    if (m->captured) {
        if (m->to == SQ(0,0)) b->castle &= ~CWQ;
        if (m->to == SQ(0,7)) b->castle &= ~CWK;
        if (m->to == SQ(7,0)) b->castle &= ~CBQ;
        if (m->to == SQ(7,7)) b->castle &= ~CBK;
    }

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
    if (m->promotion) pc = PAWN * b->side;

    b->sq[m->from] = pc;
    b->sq[m->to] = (m->flags & 1) ? 0 : m->captured;

    if (m->flags & 1) {
        int cap_sq = SQ(RANK(m->from), FILEOF(m->to));
        b->sq[cap_sq] = m->captured;
    }

    if (m->flags & 2) {
        switch (m->to) {
            case  6: b->sq[7]  = b->sq[5];  b->sq[5]  = 0; break;
            case  2: b->sq[0]  = b->sq[3];  b->sq[3]  = 0; break;
            case 62: b->sq[63] = b->sq[61]; b->sq[61] = 0; break;
            case 58: b->sq[56] = b->sq[59]; b->sq[59] = 0; break;
        }
    }

    if (PTYPE(pc) == KING)
        b->king_sq[b->side > 0 ? 0 : 1] = m->from;
}

/* ================================================================ */
void perft(Board *b, int depth, Stats *st) {
    MoveList ml;
    generate_moves(b, &ml);

    for (int i = 0; i < ml.count; i++) {
        Move *m = &ml.moves[i];
        make_move(b, m);

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

            int opp_ki = (b->side > 0) ? 0 : 1;
            if (is_attacked(b, b->king_sq[opp_ki], -b->side)) {
                st->checks++;
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

/* ================================================================ */
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
