import java.util.Arrays;

/**
 * 4th-order Butterworth low-pass filter.
 * Coefficient computation based on Exstrom Laboratories LLC
 * signal processing library (http://www.exstrom.com/journal/sigproc/).
 */
public class LowpassFilter extends Filter {

    public LowpassFilter(double Fc, double Fs) {
        if (Fc >= Fs / 2) {
            Fc = (Fs / 2) * 0.999;
        }
        // Calculate normalised cut-off
        double W = Math.min(Fc / Fs, 0.999);

        BUTTERWORTH4_NUM_COEFFICIENTS = BUTTERWORTH4_ORDER + 1;
        B = new double[BUTTERWORTH4_NUM_COEFFICIENTS];
        A = new double[BUTTERWORTH4_NUM_COEFFICIENTS];

        computeCoefficients(W, B, A);

        z = new double[BUTTERWORTH4_NUM_COEFFICIENTS];
        reset();
    }

    private void computeCoefficients(double W, double[] B, double[] A) {
        int i, j;

        // Compute binomial coefficients (Pascal's triangle for 4th order)
        int prev = BUTTERWORTH4_ORDER;
        int[] tcof = new int[BUTTERWORTH4_ORDER + 1];
        tcof[0] = 1;
        tcof[1] = BUTTERWORTH4_ORDER;
        for (i = 2; i <= BUTTERWORTH4_ORDER / 2; i++) {
            prev = (BUTTERWORTH4_ORDER - i + 1) * prev / i;
            tcof[i] = prev;
            tcof[BUTTERWORTH4_ORDER - i] = prev;
        }
        tcof[BUTTERWORTH4_ORDER - 1] = BUTTERWORTH4_ORDER;
        tcof[BUTTERWORTH4_ORDER] = 1;

        // Scaling factor for B coefficients so filter response has
        // maximum value of 1
        double omega = Math.PI * W;
        double fomega = Math.sin(omega);
        double parg0 = Math.PI / (2.0 * BUTTERWORTH4_ORDER);
        double sf = 1.0;
        for (i = 0; i < BUTTERWORTH4_ORDER / 2; i++) {
            sf *= 1.0 + fomega * Math.sin((2 * i + 1) * parg0);
        }

        fomega = Math.sin(omega / 2.0);
        sf = Math.pow(fomega, BUTTERWORTH4_ORDER) / sf;

        for (i = 0; i <= BUTTERWORTH4_ORDER; i++) {
            B[i] = sf * tcof[i];
        }

        // A coefficients via bilinear transform
        double theta = Math.PI * W;

        // Binomials
        double[] b = new double[2 * BUTTERWORTH4_ORDER];
        for (i = 0; i < BUTTERWORTH4_ORDER; i++) {
            double parg = Math.PI * (2 * i + 1) / (2.0 * BUTTERWORTH4_ORDER);
            double a_val = 1.0 + Math.sin(theta) * Math.sin(parg);
            b[2 * i] = -Math.cos(theta) / a_val;
            b[2 * i + 1] = -Math.sin(theta) * Math.cos(parg) / a_val;
        }

        // Multiply binomials together to get polynomial coefficients
        double[] a = new double[2 * BUTTERWORTH4_ORDER];
        for (i = 0; i < BUTTERWORTH4_ORDER; i++) {
            for (j = i; j > 0; --j) {
                a[2 * j] += b[2 * i] * a[2 * (j - 1)] - b[2 * i + 1] * a[2 * (j - 1) + 1];
                a[2 * j + 1] += b[2 * i] * a[2 * (j - 1) + 1] + b[2 * i + 1] * a[2 * (j - 1)];
            }
            a[0] += b[2 * i];
            a[1] += b[2 * i + 1];
        }

        // Read out A coefficients
        A[0] = 1.0;
        A[1] = a[0];
        A[2] = a[2];
        for (i = 3; i <= BUTTERWORTH4_ORDER; i++) {
            A[i] = a[2 * i - 2];
        }
    }
}
