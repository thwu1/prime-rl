/**
 * Combines delta and curvature margins into total IR margin (corrected).
 *
 */
public class RiskAggregator {

    private final double rhoDeltaCurvature;

    public RiskAggregator(double rhoDeltaCurvature) {
        this.rhoDeltaCurvature = rhoDeltaCurvature;
    }

    public double computeTotalMargin(double deltaMargin, double curvatureMargin) {
        return Math.sqrt(
            deltaMargin * deltaMargin
            + curvatureMargin * curvatureMargin
            + 2 * rhoDeltaCurvature * deltaMargin * curvatureMargin
        );
    }
}
