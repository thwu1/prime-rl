package gov.noaa.ngs.transform;

import java.io.DataInputStream;
import java.io.FileInputStream;
import java.io.IOException;

/**
 * Parses binary GTX-format grid files used for geodetic datum transformations.
 *
 * Binary format (big-endian):
 *   Header (40 bytes):
 *     latMin    (double, 8B)
 *     lonMin    (double, 8B)
 *     deltaLat  (double, 8B)
 *     deltaLon  (double, 8B)
 *     nRows     (int, 4B)
 *     nCols     (int, 4B)
 *   Data:
 *     nRows * nCols float values (4B each), row-major from (latMin, lonMin)
 */
public class GridParser {

    public static final float NULL_VALUE = -88.8888f;

    public static GridFile parse(String filePath) throws IOException {
        GridFile grid = new GridFile();
        try (DataInputStream dis = new DataInputStream(new FileInputStream(filePath))) {
            grid.latMin = dis.readDouble();
            grid.lonMin = dis.readDouble();
            grid.deltaLon = dis.readDouble();
            grid.deltaLat = dis.readDouble();
            grid.nRows = dis.readInt();
            grid.nCols = dis.readInt();

            int totalCells = grid.nRows * grid.nCols;
            grid.data = new float[totalCells];
            for (int i = 0; i < totalCells; i++) {
                grid.data[i] = (float) dis.readDouble();
            }
        }
        return grid;
    }
}
