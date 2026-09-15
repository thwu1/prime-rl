/**
 * Applies sensor calibration correction to raw accelerometer data.
 * Based on the auto-calibration methodology from the UK Biobank
 * accelerometer analysis pipeline. Compensates for per-axis sensor
 * bias (offset) and sensitivity variation (scale).
 */
public class Calibrator {

    private double[] offset;
    private double[] scale;

    public Calibrator(double[] offset, double[] scale) {
        this.offset = offset;
        this.scale = scale;
    }

    /**
     * Apply calibration correction in-place to raw sensor data.
     * Model: calibrated = (raw - offset) * scale
     */
    public void apply(double[] x, double[] y, double[] z) {
        for (int i = 0; i < x.length; i++) {
            x[i] = x[i] * scale[0] - offset[0];
            y[i] = y[i] * scale[1] - offset[1];
            z[i] = z[i] * scale[2] - offset[2];
        }
    }

    /**
     * Compute root-mean-square calibration residual.
     * For well-calibrated stationary data, vector magnitude should be close to 1g.
     */
    public static double computeResidualError(double[] x, double[] y, double[] z) {
        double sumSqErr = 0;
        for (int i = 0; i < x.length; i++) {
            double vm = Math.sqrt(x[i] * x[i] + y[i] * y[i] + z[i] * z[i]);
            sumSqErr += (vm - 1.0) * (vm - 1.0);
        }
        return Math.sqrt(sumSqErr / x.length);
    }
}
