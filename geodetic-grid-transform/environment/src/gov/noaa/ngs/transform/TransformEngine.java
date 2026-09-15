package gov.noaa.ngs.transform;

/**
 * Command-line entry point for the geodetic datum transformation engine.
 *
 * Usage: java gov.noaa.ngs.transform.TransformEngine lat lon srcDatum destDatum
 *
 * Input longitude uses negative-West convention.
 * Output: destLat,destLon,sigLat,sigLon
 */
public class TransformEngine {

    public static void main(String[] args) {
        if (args.length < 4) {
            System.err.println("Usage: TransformEngine <lat> <lon> <srcDatum> <destDatum>");
            System.err.println("  lat: decimal degrees (positive North)");
            System.err.println("  lon: decimal degrees (negative West)");
            System.exit(1);
        }

        try {
            double lat = Double.parseDouble(args[0]);
            double lon = Double.parseDouble(args[1]);
            String srcDatum = args[2];
            String destDatum = args[3];

            String configPath = "/app/config/regions.properties";
            String gridPath = "/app/data/grids";

            // Convert to positive-East longitude for internal processing
            double eLon = lon < 0 ? lon + 360.0 : lon;

            RegionConfig config = new RegionConfig(configPath);
            DatumChainTransformer transformer = new DatumChainTransformer(config, gridPath);

            TransformResult result = transformer.transform(lat, eLon, srcDatum, destDatum);

            // Convert output longitude back to negative-West if input was West
            double outLon = result.lon;
            if (lon < 0 && outLon > 180.0) {
                outLon -= 360.0;
            }

            System.out.println(String.format("%.10f,%.10f,%.6f,%.6f",
                    result.lat, outLon, result.sigLat, result.sigLon));

        } catch (Exception e) {
            System.err.println("Error: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }
    }
}
