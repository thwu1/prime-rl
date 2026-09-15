package gov.noaa.ngs.transform;

import java.io.FileInputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

/**
 * Loads and provides access to region definitions, datum sequences,
 * and geographic bounds from a properties configuration file.
 */
public class RegionConfig {

    private String[] regions;
    private double[] bounds;
    private Map<String, String[]> datumMap;

    public RegionConfig(String configPath) throws IOException {
        Properties props = new Properties();
        try (FileInputStream fis = new FileInputStream(configPath)) {
            props.load(fis);
        }

        String regionStr = props.getProperty("regions");
        regions = regionStr.split(",");
        for (int i = 0; i < regions.length; i++) {
            regions[i] = regions[i].trim();
        }

        String boundsStr = props.getProperty("bounds");
        String[] boundsParts = boundsStr.split(",");
        bounds = new double[boundsParts.length];
        for (int i = 0; i < boundsParts.length; i++) {
            bounds[i] = Double.parseDouble(boundsParts[i].trim());
        }

        datumMap = new HashMap<>();
        for (String region : regions) {
            String datumStr = props.getProperty(region + ".datum");
            if (datumStr != null) {
                String[] datums = datumStr.split(",");
                for (int i = 0; i < datums.length; i++) {
                    datums[i] = datums[i].trim();
                }
                datumMap.put(region, datums);
            }
        }
    }

    /**
     * Finds the region containing the given coordinate.
     * Longitude should be in positive-East convention for comparison
     * against the configured region bounds.
     *
     * @return region name, or null if no region contains the point
     */
    public String findRegion(double lat, double lon) {
        double eLon = lon > 180 ? lon - 360.0 : lon;

        for (int i = 0; i < regions.length; i++) {
            int idx = i * 4;
            if (lat >= bounds[idx] && lat <= bounds[idx + 1] &&
                eLon >= bounds[idx + 2] && eLon <= bounds[idx + 3]) {
                return regions[i];
            }
        }
        return null;
    }

    public String[] getDatums(String region) {
        return datumMap.get(region);
    }

    public String[] getRegions() {
        return regions;
    }
}
