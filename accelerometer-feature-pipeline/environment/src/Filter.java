import java.util.Arrays;

/**
 * Base class for IIR digital filters.
 * Implements Direct Form II Transposed structure for filtering.
 * Subclasses compute B (feedforward) and A (feedback) coefficients.
 */
public class Filter {

    protected static final int BUTTERWORTH4_ORDER = 4;
    protected int BUTTERWORTH4_NUM_COEFFICIENTS;
    protected double[] B;
    protected double[] A;
    protected double[] z;

    public void reset() {
        if (z != null) Arrays.fill(z, 0);
    }

    /**
     * Apply IIR filter in-place using Direct Form II Transposed.
     * Equivalent to scipy.signal.lfilter(B, A, signal).
     */
    public void filter(double[] signal) {
        if (B == null || A == null || z == null) return;
        int n = B.length;
        for (int i = 0; i < signal.length; i++) {
            double input = signal[i];
            double output = B[0] * input + z[0];
            for (int j = 0; j < n - 2; j++) {
                z[j] = B[j + 1] * input - A[j + 1] * output + z[j + 1];
            }
            z[n - 2] = B[n - 1] * input - A[n - 1] * output;
            signal[i] = output;
        }
    }
}
