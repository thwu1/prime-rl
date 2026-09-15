/**
 * Sensitivity data holder.
 *
 */
public class Sensitivity {
    public final String riskType;
    public final String currency;
    public final String subCurve;
    public final String tenor;
    public final double value;

    public Sensitivity(String riskType, String currency, String subCurve, String tenor, double value) {
        this.riskType = riskType;
        this.currency = currency;
        this.subCurve = subCurve;
        this.tenor = tenor;
        this.value = value;
    }

    @Override
    public String toString() {
        return riskType + "/" + currency + "/" + subCurve + "/" + tenor + "=" + value;
    }
}
