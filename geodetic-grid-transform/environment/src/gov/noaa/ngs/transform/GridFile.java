package gov.noaa.ngs.transform;

/**
 * Represents a parsed binary GTX grid file.
 * Contains header metadata and grid values in row-major order.
 */
public class GridFile {
    public double latMin;
    public double lonMin;
    public double deltaLat;
    public double deltaLon;
    public int nRows;
    public int nCols;
    public float[] data;

    public double getLatMax() {
        return latMin + (nRows - 1) * deltaLat;
    }

    public double getLonMax() {
        return lonMin + (nCols - 1) * deltaLon;
    }

    /**
     * Gets the value at the given grid row and column indices.
     * Row 0 corresponds to the maximum latitude (northernmost row).
     */
    public float getValue(int row, int col) {
        return data[(nRows - 1 - row) * nCols + col];
    }
}
