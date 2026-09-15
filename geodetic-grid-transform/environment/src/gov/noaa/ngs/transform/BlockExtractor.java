package gov.noaa.ngs.transform;

/**
 * Extracts a 3x3 block of grid values surrounding a query point
 * and computes the interpolation coordinates within the block.
 */
public class BlockExtractor {

    public static final int BLOCK_SIZE = 3;
    public static final int MISSING_DATA = -999;

    /**
     * Extracts a 3x3 block of grid values surrounding the query point.
     * The block is positioned so that the query point falls within
     * the central cell (between grid indices 1 and 2 of the block).
     *
     * @return flat array of 9 values in row-major order, or null if out of bounds
     */
    public static double[] extractBlock(GridFile grid, double lat, double lon) {
        double fracRow = (lat - grid.latMin) / grid.deltaLat;
        double fracCol = (lon - grid.lonMin) / grid.deltaLon;

        int baseRow = (int) Math.round(fracRow) - 1;
        int baseCol = (int) Math.round(fracCol) - 1;

        if (baseRow < 0 || baseRow + 2 >= grid.nRows ||
            baseCol < 0 || baseCol + 2 >= grid.nCols) {
            return null;
        }

        double[] block = new double[BLOCK_SIZE * BLOCK_SIZE];
        for (int i = 0; i < BLOCK_SIZE; i++) {
            for (int j = 0; j < BLOCK_SIZE; j++) {
                float val = grid.getValue(baseRow + i, baseCol + j);
                if (Math.abs(val - GridParser.NULL_VALUE) < 0.001f) {
                    block[i * BLOCK_SIZE + j] = MISSING_DATA;
                } else {
                    block[i * BLOCK_SIZE + j] = val;
                }
            }
        }

        return block;
    }

    /**
     * Returns the interpolation coordinates (x, y) within the 3x3 block.
     * Coordinates are relative to the block's base row/col, typically
     * falling in [1, 2) for a properly centered block.
     */
    public static double[] getInterpPoint(GridFile grid, double lat, double lon) {
        double fracRow = (lat - grid.latMin) / grid.deltaLat;
        double fracCol = (lon - grid.lonMin) / grid.deltaLon;

        int baseRow = (int) Math.round(fracRow) - 1;
        int baseCol = (int) Math.round(fracCol) - 1;

        double x = fracRow - baseRow;
        double y = fracCol - baseCol;

        return new double[]{x, y};
    }

    /**
     * Ranks a 3x3 block based on presence of missing data.
     *
     * @return 3 = full block usable (biquadratic), 2 = center 2x2 usable (bilinear), 1 = unusable
     */
    public static int rankBlock(double[] block) {
        boolean hasMissing = false;
        for (double v : block) {
            if ((int) v == MISSING_DATA) {
                hasMissing = true;
                break;
            }
        }
        if (!hasMissing) return 3;

        // Check center 2x2 sub-block: indices (1,1), (1,2), (2,1), (2,2)
        int[] center = {4, 5, 7, 8};
        for (int idx : center) {
            if ((int) block[idx] == MISSING_DATA) return 1;
        }
        return 2;
    }
}
