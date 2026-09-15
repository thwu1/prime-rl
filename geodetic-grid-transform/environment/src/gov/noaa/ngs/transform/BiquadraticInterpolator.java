package gov.noaa.ngs.transform;

/**
 * Implements biquadratic (Lagrange) interpolation on a 3x3 grid block
 * and bilinear interpolation as a fallback for 2x2 blocks.
 *
 * Biquadratic interpolation uses the tensor product of 1D quadratic
 * Lagrange polynomials through nodes at positions 0, 1, 2.
 */
public class BiquadraticInterpolator {

    /**
     * Performs biquadratic interpolation on a 3x3 block.
     *
     * @param x row interpolation coordinate (typically in [1, 2))
     * @param y column interpolation coordinate (typically in [1, 2))
     * @param block 9 values in row-major order
     * @return interpolated value
     */
    public static double interpolate(double x, double y, double[] block) {
        double result = 0.0;
        for (int i = 0; i < 3; i++) {
            double rowVal = 0.0;
            for (int j = 0; j < 3; j++) {
                rowVal += block[i * 3 + j] * lagrangeBasis(j, y);
            }
            result += rowVal * lagrangeBasis(i, x);
        }
        return result;
    }

    /**
     * Computes the Lagrange basis polynomial value for the given index
     * and parameter t. Nodes are at t = 0, 1, 2.
     *
     * L_0(t), L_1(t), L_2(t) such that L_i(j) = delta_{ij}
     */
    private static double lagrangeBasis(int index, double t) {
        switch (index) {
            case 0:
                return t * (t - 1) / 2.0;
            case 1:
                return -t * (t - 2);
            case 2:
                return (t - 1) * (t - 2) / 2.0;
            default:
                throw new IllegalArgumentException("Index must be 0, 1, or 2");
        }
    }

    /**
     * Performs bilinear interpolation on a 2x2 block.
     *
     * @param x row coordinate in [0, 1]
     * @param y column coordinate in [0, 1]
     * @param block2x2 4 values: [0]=bottom-left, [1]=bottom-right, [2]=top-left, [3]=top-right
     * @return interpolated value
     */
    public static double bilinear(double x, double y, double[] block2x2) {
        return (1 - x) * (1 - y) * block2x2[0]
             + (1 - x) * y * block2x2[1]
             + x * (1 - y) * block2x2[2]
             + x * y * block2x2[3];
    }
}
