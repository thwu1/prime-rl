package com.kelseyde.calvin.evaluation;

import com.kelseyde.calvin.board.Piece;
import com.kelseyde.calvin.board.Bits.Square;
import com.kelseyde.calvin.board.Bits.File;

/**
 * A single NNUE input feature: a piece of a given type and colour
 * on a given square.
 */
public record Feature(Piece piece, int square, boolean white) {

    /**
     * Computes the feature index from the given perspective, relative
     * to the perspective's king square.
     *
     * Total feature space: 2 (relative colour) × 6 (piece type) × 64 (square) = 768.
     */
    public int index(boolean whitePerspective, int kingSquare) {
        int colourOffset = (white == whitePerspective) ? 0 : 1;
        int pieceIndex   = piece.index();

        int sq     = whitePerspective ? square     : Square.flipRank(square);
        int kingAdj = whitePerspective ? kingSquare : Square.flipRank(kingSquare);

        if (File.of(kingAdj) > 3) {
            sq = Square.flipFile(sq);
        }

        return colourOffset * Piece.COUNT * Square.COUNT
             + pieceIndex   * Square.COUNT
             + sq;
    }
}
