package conjanalysis;

/**
 * Data holder for parsed CCSDS Conjunction Data Message fields.
 *
 */
public class CdmData {
    public String tca = "";
    public double missDistance;
    public String name1 = "", name2 = "";
    public double[] pos1 = new double[3];
    public double[] vel1 = new double[3];
    public double[] pos2 = new double[3];
    public double[] vel2 = new double[3];
    /** 3x3 position covariance for object 1 in its local frame (m^2) */
    public double[][] cov1 = new double[3][3];
    /** 3x3 position covariance for object 2 in its local frame (m^2) */
    public double[][] cov2 = new double[3][3];
}
