package gov.noaa.ngs.transform;

/**
 * Holds the result of a datum transformation:
 * transformed latitude/longitude and accumulated error estimates.
 */
public class TransformResult {
    public double lat;
    public double lon;
    public double sigLat;
    public double sigLon;

    public TransformResult(double lat, double lon) {
        this.lat = lat;
        this.lon = lon;
        this.sigLat = 0.0;
        this.sigLon = 0.0;
    }

    @Override
    public String toString() {
        return String.format("%.10f,%.10f,%.6f,%.6f", lat, lon, sigLat, sigLon);
    }
}
