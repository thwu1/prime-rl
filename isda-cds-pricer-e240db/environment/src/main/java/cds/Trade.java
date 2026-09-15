package cds;

/**
 * CDS trade specification.
 *
 */
public class Trade {
    public String id;
    public int buySell;          // +1 for BUY, -1 for SELL
    public String startDate;     // ISO format YYYY-MM-DD
    public String endDate;       // ISO format YYYY-MM-DD
    public int frequencyMonths;
    public String valuationDate;
    public String stepinDate;
    public double recoveryRate;
    public double notional;
    public double fixedRate;
}
