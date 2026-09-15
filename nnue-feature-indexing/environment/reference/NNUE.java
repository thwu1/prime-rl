/**
 * Excerpted from Calvin chess engine — NNUE evaluation subsystem.
 * Source: https://github.com/kelseyde/calvin-chess-engine
 *
 * Not all referenced types are included (Board, Move, Accumulator,
 * AccumulatorUpdate).  Their behaviour can be inferred from usage.
 *
 * Square numbering: LERF  (a1 = 0, b1 = 1, …, h1 = 7, a2 = 8, …, h8 = 63).
 */
package com.kelseyde.calvin.evaluation;

import com.kelseyde.calvin.board.*;
import com.kelseyde.calvin.board.Bits.File;
import com.kelseyde.calvin.board.Bits.Rank;
import com.kelseyde.calvin.board.Bits.Square;

public class NNUE {

    // ── Network architecture ────────────────────────────────────────

    /** Input features per bucket: 2 colours × 6 piece types × 64 squares. */
    private static final int INPUT_SIZE = 768;

    /**
     * King input-bucket map.  Indexed by the perspective-adjusted king
     * square (white squares as-is; black squares rank-flipped first).
     * Determines which weight slice the accumulator uses.
     */
    private static final int[] INPUT_BUCKETS = {
            0, 1, 2, 3, 3, 2, 1, 0,
            4, 4, 5, 5, 5, 5, 4, 4,
            6, 6, 6, 6, 6, 6, 6, 6,
            6, 6, 6, 6, 6, 6, 6, 6,
            6, 6, 6, 6, 6, 6, 6, 6,
            7, 7, 7, 7, 7, 7, 7, 7,
            7, 7, 7, 7, 7, 7, 7, 7,
            7, 7, 7, 7, 7, 7, 7, 7,
    };

    private static final int NUM_BUCKETS = 8;

    // ── King bucket / mirror helpers ────────────────────────────────

    /** Input bucket for a king square, perspective-adjusted for colour. */
    private int kingBucket(int kingSquare, boolean white) {
        kingSquare = white ? kingSquare : Square.flipRank(kingSquare);
        return INPUT_BUCKETS[kingSquare];
    }

    /** True when the king is on files e–h, triggering horizontal mirroring. */
    private boolean shouldMirror(int kingSquare) {
        return File.of(kingSquare) > 3;
    }

    // ── Refresh detection ───────────────────────────────────────────

    /**
     * A full accumulator refresh is needed for the moving side's own
     * perspective when its king crosses a bucket or mirror boundary.
     * Non-king moves never trigger a refresh for either perspective.
     */
    private boolean mirrorChanged(Board board, Move move, Piece piece) {
        if (piece != Piece.KING) return false;
        int prev = move.from();
        int curr = castleAwareKingDest(move);
        return shouldMirror(prev) != shouldMirror(curr);
    }

    private boolean bucketChanged(Board board, Move move, Piece piece, boolean white) {
        if (piece != Piece.KING) return false;
        int prev = move.from();
        int curr = castleAwareKingDest(move);
        return kingBucket(prev, white) != kingBucket(curr, white);
    }

    /** For castling, the king's real destination differs from the UCI to-square. */
    private int castleAwareKingDest(Move move) {
        if (!move.isCastling()) return move.to();
        boolean kingside = File.of(move.to()) > File.of(move.from());
        int rank = Rank.of(move.from());
        return kingside ? (rank * 8 + 6) : (rank * 8 + 2);
    }

    /**
     * Post-move king square for a given perspective.
     * If this is the opponent's move, or a non-king move, returns the
     * current king square unchanged.
     */
    private int kingSquare(Board board, Move move, Piece piece, boolean white) {
        if (white != board.isWhite() || piece != Piece.KING) {
            return board.kingSquare(white);
        }
        return castleAwareKingDest(move);
    }

    // ── Full refresh ────────────────────────────────────────────────

    /**
     * Recomputes the accumulator for one perspective from scratch
     * by iterating over every piece on the board and adding its feature.
     */
    private void fullRefresh(Board board, Accumulator acc,
                             boolean whitePerspective, int bucket) {
        short[] weights = network.inputWeights()[bucket];
        int kingSquare = board.kingSquare(whitePerspective);
        boolean mirror = shouldMirror(
                whitePerspective ? kingSquare : Square.flipRank(kingSquare));

        for (int colourIdx = 0; colourIdx < 2; colourIdx++) {
            boolean white = colourIdx == 0;
            for (int pieceIdx = 0; pieceIdx < Piece.COUNT; pieceIdx++) {
                Piece piece = Piece.values()[pieceIdx];
                long bb = board.getPieces(piece, white);
                while (bb != 0) {
                    int sq = Bits.next(bb);
                    Feature f = new Feature(piece, sq, white);
                    acc.add(weights, f.index(whitePerspective, kingSquare),
                            whitePerspective);
                    bb = Bits.pop(bb);
                }
            }
        }
    }

    // ── Incremental updates by move type ────────────────────────────

    /** Quiet move or promotion: sub piece@from, add (promoted) piece@to. */
    private AccumulatorUpdate handleStandardMove(Board board, Move move,
                                                 boolean white) {
        Piece piece = board.pieceAt(move.from());
        Piece newPiece = move.isPromotion() ? move.promoPiece() : piece;
        AccumulatorUpdate u = new AccumulatorUpdate();
        u.pushSub(new Feature(piece,    move.from(), white));
        u.pushAdd(new Feature(newPiece, move.to(),   white));
        return u;
    }

    /** Castle: move king and rook to their standard destinations. */
    private AccumulatorUpdate handleCastleMove(Move move, boolean white) {
        boolean kingside = File.of(move.to()) > File.of(move.from());
        int rank = Rank.of(move.from());

        int kingFrom = move.from();
        int kingTo   = kingside ? (rank * 8 + 6) : (rank * 8 + 2);
        int rookFrom = kingside ? (rank * 8 + 7) : (rank * 8 + 0);
        int rookTo   = kingside ? (rank * 8 + 5) : (rank * 8 + 3);

        AccumulatorUpdate u = new AccumulatorUpdate();
        u.pushSub(new Feature(Piece.KING, kingFrom, white));
        u.pushSub(new Feature(Piece.ROOK, rookFrom, white));
        u.pushAdd(new Feature(Piece.KING, kingTo,   white));
        u.pushAdd(new Feature(Piece.ROOK, rookTo,   white));
        return u;
    }

    /** Capture (including en passant and promotion-capture). */
    private AccumulatorUpdate handleCapture(Board board, Move move,
                                            boolean white) {
        Piece piece    = board.pieceAt(move.from());
        Piece newPiece = move.isPromotion() ? move.promoPiece() : piece;
        Piece captured = move.isEnPassant() ? Piece.PAWN
                                            : board.pieceAt(move.to());
        int captureSquare = move.to();
        if (move.isEnPassant()) {
            captureSquare = white ? move.to() - 8 : move.to() + 8;
        }
        AccumulatorUpdate u = new AccumulatorUpdate();
        u.pushSub(new Feature(piece,    move.from(),    white));
        u.pushAdd(new Feature(newPiece, move.to(),      white));
        u.pushSub(new Feature(captured, captureSquare, !white));
        return u;
    }

    // ── Top-level move handler ──────────────────────────────────────

    /**
     * Called after a move is made.  Determines the move type, computes the
     * feature delta, and either incrementally updates or fully refreshes
     * each accumulator half.
     *
     * When performing an incremental update, Feature.index() is called
     * with the perspective's *pre-move* king square.
     */
    public void makeMove(Board board, Move move) {
        boolean white = board.isWhite();
        Piece piece = board.pieceAt(move.from());

        AccumulatorUpdate update;
        if (move.isCastling())
            update = handleCastleMove(move, white);
        else if (board.isCapture(move))
            update = handleCapture(board, move, white);
        else
            update = handleStandardMove(board, move, white);

        boolean refresh =
            mirrorChanged(board, move, piece)
         || bucketChanged(board, move, piece, white);

        // For each perspective:
        //   if refresh needed → recompute all features via fullRefresh()
        //   otherwise         → apply delta using pre-move king position
    }
}
