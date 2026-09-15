
import java.util.function.Function;

/**
 * Multi-dimensional Newton-Raphson solver with finite-difference Jacobian.
 * Used for curve calibration: find zero rates such that all instrument PVs = 0.
 */
public class NewtonSolver {

    private static final double BUMP = 1.0e-7;
    private static final double TOLERANCE = 1.0e-12;
    private static final int MAX_ITER = 200;

    /**
     * Find x such that f(x) = 0.
     *
     * @param n  dimension of the problem
     * @param f  vector function to zero (maps parameters to instrument PVs)
     * @param x0 initial guess
     * @return   solution vector
     */
    public static double[] solve(int n,
                                 Function<double[], double[]> f,
                                 double[] x0) {
        double[] x = x0.clone();

        for (int iter = 0; iter < MAX_ITER; iter++) {
            double[] fx = f.apply(x);

            // Check convergence
            double maxF = 0.0;
            for (double v : fx) maxF = Math.max(maxF, Math.abs(v));
            if (maxF < TOLERANCE) {
                System.out.printf("    Converged in %d iterations "
                    + "(max|f| = %.2e)%n", iter + 1, maxF);
                return x;
            }

            // Finite-difference Jacobian
            double[][] J = new double[n][n];
            for (int j = 0; j < n; j++) {
                x[j] += BUMP;
                double[] fBumped = f.apply(x);
                x[j] -= BUMP;
                for (int i = 0; i < n; i++) {
                    J[i][j] = (fBumped[i] - fx[i]) / BUMP;
                }
            }

            // Solve J * dx = -fx via Gaussian elimination
            double[] negFx = new double[n];
            for (int i = 0; i < n; i++) negFx[i] = -fx[i];
            double[] dx = gaussianElimination(J, negFx, n);

            // Newton update
            for (int i = 0; i < n; i++) x[i] += dx[i];
        }

        double[] fx = f.apply(x);
        double maxF = 0.0;
        for (double v : fx) maxF = Math.max(maxF, Math.abs(v));
        System.err.printf("    WARNING: did not converge after %d "
            + "iterations (max|f| = %.2e)%n", MAX_ITER, maxF);
        return x;
    }

    private static double[] gaussianElimination(double[][] A,
                                                 double[] b, int n) {
        // Build augmented matrix [A | b]
        double[][] aug = new double[n][n + 1];
        for (int i = 0; i < n; i++) {
            System.arraycopy(A[i], 0, aug[i], 0, n);
            aug[i][n] = b[i];
        }

        // Forward elimination with partial pivoting
        for (int col = 0; col < n; col++) {
            int pivotRow = col;
            for (int row = col + 1; row < n; row++) {
                if (Math.abs(aug[row][col]) > Math.abs(aug[pivotRow][col])) {
                    pivotRow = row;
                }
            }
            double[] tmp = aug[col];
            aug[col] = aug[pivotRow];
            aug[pivotRow] = tmp;

            if (Math.abs(aug[col][col]) < 1e-20) {
                throw new RuntimeException(
                    "Singular Jacobian at column " + col);
            }

            for (int row = col + 1; row < n; row++) {
                double factor = aug[row][col] / aug[col][col];
                for (int j = col; j <= n; j++) {
                    aug[row][j] -= factor * aug[col][j];
                }
            }
        }

        // Back substitution
        double[] x = new double[n];
        for (int i = n - 1; i >= 0; i--) {
            x[i] = aug[i][n];
            for (int j = i + 1; j < n; j++) {
                x[i] -= aug[i][j] * x[j];
            }
            x[i] /= aug[i][i];
        }
        return x;
    }
}
