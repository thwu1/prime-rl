package gov.noaa.ngs.transform;

import java.io.IOException;

/**
 * Chains datum transformations through ordered datum sequences.
 * Supports both forward (older to newer) and backward (newer to older) transformations.
 * Each step interpolates shift values from grid files and applies them to the coordinates.
 */
public class DatumChainTransformer {

    private RegionConfig config;
    private String gridBasePath;

    public DatumChainTransformer(RegionConfig config, String gridBasePath) {
        this.config = config;
        this.gridBasePath = gridBasePath;
    }

    /**
     * Transforms coordinates from srcDatum to destDatum by chaining
     * through intermediate datums in the region's datum sequence.
     */
    public TransformResult transform(double lat, double lon, String srcDatum, String destDatum)
            throws IOException {

        String region = config.findRegion(lat, lon);
        if (region == null) {
            throw new IllegalArgumentException("No suitable region found for datum transformation");
        }

        String[] datums = config.getDatums(region);
        int srcIdx = indexOf(datums, srcDatum);
        int destIdx = indexOf(datums, destDatum);

        if (srcIdx == -1 || destIdx == -1) {
            throw new IllegalArgumentException("Source or destination datum not found for " + region);
        }

        TransformResult result = new TransformResult(lat, lon);

        if (destIdx > srcIdx) {
            // Forward transformation (to newer datums)
            for (int i = srcIdx; i < destIdx; i++) {
                applyForwardStep(result, region, datums[i], datums[i + 1]);
            }
        } else {
            // Backward transformation (to older datums)
            for (int i = srcIdx; i > destIdx; i--) {
                applyBackwardStep(result, region, datums[i - 1], datums[i]);
            }
        }

        // Finalize errors: take square root of accumulated values
        result.sigLat = Math.sqrt(result.sigLat);
        result.sigLon = Math.sqrt(result.sigLon);

        return result;
    }

    private void applyForwardStep(TransformResult result, String region,
            String fromDatum, String toDatum) throws IOException {

        double latShift = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lat", "trn");
        double lonShift = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lon", "trn");
        double latErr = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lat", "err");
        double lonErr = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lon", "err");

        // Apply shift (shifts are in arcseconds, convert to degrees)
        result.lat += latShift / 3600.0;
        result.lon += lonShift / 3600.0;

        // Accumulate error estimates
        result.sigLat += latErr;
        result.sigLon += lonErr;
    }

    private void applyBackwardStep(TransformResult result, String region,
            String fromDatum, String toDatum) throws IOException {

        double latShift = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lat", "trn");
        double lonShift = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lon", "trn");
        double latErr = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lat", "err");
        double lonErr = interpolateGrid(result.lat, result.lon, region, fromDatum, toDatum, "lon", "err");

        // Apply inverse shift for backward transformation
        result.lat += latShift / 3600.0;
        result.lon += lonShift / 3600.0;

        // Accumulate error estimates
        result.sigLat += latErr;
        result.sigLon += lonErr;
    }

    private double interpolateGrid(double lat, double lon, String region,
            String fromDatum, String toDatum, String parm, String type) throws IOException {

        String gridFile = buildGridPath(region, fromDatum, toDatum, parm, type);
        GridFile grid = GridParser.parse(gridFile);

        double[] block = BlockExtractor.extractBlock(grid, lat, lon);
        if (block == null) {
            throw new IOException("Point out of grid bounds for file: " + gridFile);
        }

        double[] coord = BlockExtractor.getInterpPoint(grid, lat, lon);
        int rank = BlockExtractor.rankBlock(block);

        if (rank == 3) {
            return BiquadraticInterpolator.interpolate(coord[0], coord[1], block);
        } else if (rank == 2) {
            // Fallback to bilinear on center 2x2 sub-block
            double[] block2x2 = {block[4], block[5], block[7], block[8]};
            double bx = coord[0] - 1.0;
            double by = coord[1] - 1.0;
            return BiquadraticInterpolator.bilinear(bx, by, block2x2);
        } else {
            throw new IOException("Insufficient grid data for interpolation: " + gridFile);
        }
    }

    private String buildGridPath(String region, String fromDatum, String toDatum,
            String parm, String type) {
        String cleanFrom = fromDatum.replaceAll("[()]", "").toLowerCase();
        String cleanTo = toDatum.replaceAll("[()]", "").toLowerCase();
        return gridBasePath + "/nadcon5." + region.toLowerCase() + "."
                + cleanFrom + "." + cleanTo + "." + parm + type + ".b";
    }

    private int indexOf(String[] array, String value) {
        for (int i = 0; i < array.length; i++) {
            if (array[i].equalsIgnoreCase(value)) return i;
        }
        return -1;
    }
}
