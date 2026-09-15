package calibrator;


import java.util.*;

/**
 * Bucketed PV01 computation for portfolio positions against calibrated curves.
 */
public class SensitivityEngine {

    private final Pricer pricer;

    public SensitivityEngine(Pricer pricer) {
        this.pricer = pricer;
    }

    /**
     * Compute bucketed PV01 for a swap position.
     *
     * @param type     instrument type: "OIS", "IRS6M", or "BS3M6M"
     * @param tenor    swap maturity in years
     * @param rate     fixed rate or spread
     * @param notional position notional amount
     * @return map from curve name to array of PV01 values (one per node)
     */
    public Map<String, double[]> computePV01(String type, double tenor,
                                              double rate, double notional) {
        // TODO: Implement bump-and-revalue PV01 computation
        throw new UnsupportedOperationException(
            "SensitivityEngine.computePV01 not yet implemented");
    }
}
