/**
 * Combines delta and curvature margins into total IR margin.
 *
 */
public class RiskAggregator {

    private final double rhoDeltaCurvature;

    public RiskAggregator(double rhoDeltaCurvature) {
        this.rhoDeltaCurvature = rhoDeltaCurvature;
    }

    /**
     * Computes total IR margin from delta and curvature margins.
     */
    public double computeTotalMargin(double deltaMargin, double curvatureMargin) {
        return deltaMargin + curvatureMargin;
    }
}
