package conjanalysis;

/**
 * Collision probability computation and conjunction analysis.
 *
 */
public class CollisionAnalyzer {

    public static double computePc(double xm, double ym,
                                    double sigmaX, double sigmaY,
                                    double radius) {
        double dm2 = xm * xm + ym * ym;
        double dm = Math.sqrt(dm2);
        double R2 = radius * radius;
        double sx2 = sigmaX * sigmaX;
        double sy2 = sigmaY * sigmaY;
        double norm2pi = 2.0 * Math.PI * sigmaX * sigmaY;

        double a, b;
        if (dm <= radius) {
            a = 0.0;
            b = 2.0 * Math.PI;
        } else {
            double alpha = Math.atan2(ym, xm);
            double halfWidth = Math.asin(radius / dm);
            a = alpha - halfWidth;
            b = alpha + halfWidth;
        }

        int maxLevels = 25;
        double[][] T = new double[maxLevels][maxLevels];
        double h = b - a;
        T[0][0] = h / 2.0 * (integrand(a, xm, ym, sx2, sy2, dm2, R2, norm2pi)
                            + integrand(b, xm, ym, sx2, sy2, dm2, R2, norm2pi));

        for (int n = 1; n < maxLevels; n++) {
            h = (b - a) / (1 << n);
            int numNew = 1 << (n - 1);
            double sum = 0.0;
            for (int k = 0; k < numNew; k++) {
                double x = a + (2 * k + 1) * h;
                sum += integrand(x, xm, ym, sx2, sy2, dm2, R2, norm2pi);
            }
            T[n][0] = T[n - 1][0] / 2.0 + h * sum;

            for (int m = 1; m <= n; m++) {
                double factor = Math.pow(4.0, m);
                T[n][m] = (factor * T[n][m - 1] - T[n - 1][m - 1]) / (factor - 1.0);
            }

            if (n >= 5) {
                double val = T[n][n];
                double absVal = Math.abs(val);
                double err1 = Math.abs(T[n][n] - T[n - 1][n - 1]);
                double err2 = Math.abs(T[n][n] - T[n][n - 1]);
                double tol = 1e-14 * absVal + 1e-300;
                if (err1 < tol && err2 < tol) {
                    return Math.max(0.0, val);
                }
            }
        }
        return Math.max(0.0, T[maxLevels - 1][maxLevels - 1]);
    }

    static double integrand(double phi, double xm, double ym,
                             double sx2, double sy2, double dm2, double R2,
                             double norm2pi) {
        double cp = Math.cos(phi);
        double sp = Math.sin(phi);
        double invSr2 = cp * cp / sx2 + sp * sp / sy2;
        double sr2 = 1.0 / invSr2;
        double p = xm * cp + ym * sp;
        double delta = p * p - dm2 + R2;
        if (delta < 0) return 0.0;
        double sqrtDelta = Math.sqrt(delta);
        double r1 = Math.max(0.0, p - sqrtDelta);
        double r2 = Math.max(0.0, p + sqrtDelta);
        if (r2 <= r1) return 0.0;
        double e1 = r1 * r1 / (2.0 * sr2);
        double e2 = r2 * r2 / (2.0 * sr2);
        double exp1 = (e1 < 700) ? Math.exp(-e1) : 0.0;
        double exp2 = (e2 < 700) ? Math.exp(-e2) : 0.0;
        return sr2 / norm2pi * (exp1 - exp2);
    }

    public static AnalysisResult analyzeCdm(CdmData cdm, double combinedHbr) {
        double[] relPos = sub(cdm.pos1, cdm.pos2);
        double[] relVel = sub(cdm.vel1, cdm.vel2);
        double relVelMag = norm(relVel);
        double[] relPosM = {relPos[0] * 1000, relPos[1] * 1000, relPos[2] * 1000};

        double[][] cov1I = rotateRTNtoInertial(cdm.cov1, cdm.pos1, cdm.vel1);
        double[][] cov2I = rotateRTNtoInertial(cdm.cov2, cdm.pos2, cdm.vel2);

        double[][] combCov = new double[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                combCov[i][j] = cov1I[i][j] + cov2I[i][j];

        double[] eAlong = scale(relVel, 1.0 / relVelMag);
        double dotAlongPos = dot(relPosM, eAlong);
        double[] relPosPerp = new double[3];
        for (int i = 0; i < 3; i++)
            relPosPerp[i] = relPosM[i] - dotAlongPos * eAlong[i];

        double[] seed = (Math.abs(eAlong[0]) < 0.9)
            ? new double[]{1, 0, 0} : new double[]{0, 1, 0};
        double d = dot(seed, eAlong);
        double[] e1 = new double[3];
        for (int i = 0; i < 3; i++) e1[i] = seed[i] - d * eAlong[i];
        double n1 = norm(e1);
        for (int i = 0; i < 3; i++) e1[i] /= n1;
        double[] e2 = cross(eAlong, e1);
        double n2 = norm(e2);
        for (int i = 0; i < 3; i++) e2[i] /= n2;

        double missX = dot(relPosPerp, e1);
        double missY = dot(relPosPerp, e2);

        double[][] c2d = new double[2][2];
        c2d[0][0] = quadForm(combCov, e1, e1);
        c2d[0][1] = quadForm(combCov, e1, e2);
        c2d[1][0] = c2d[0][1];
        c2d[1][1] = quadForm(combCov, e2, e2);

        double trace = c2d[0][0] + c2d[1][1];
        double det = c2d[0][0] * c2d[1][1] - c2d[0][1] * c2d[1][0];
        double disc = Math.sqrt(Math.max(0, trace * trace - 4 * det));
        double lam1 = (trace + disc) / 2.0;
        double lam2 = (trace - disc) / 2.0;

        double[][] V = eigenVecs2x2(c2d, lam1, lam2);
        double xm = missX * V[0][0] + missY * V[1][0];
        double ym = missX * V[0][1] + missY * V[1][1];

        double sA = Math.sqrt(Math.max(lam1, 0));
        double sB = Math.sqrt(Math.max(lam2, 0));

        double pc = computePc(xm, ym, sA, sB, combinedHbr);
        return new AnalysisResult(pc, relVelMag);
    }

    public static String classifyRisk(double pc) {
        if (pc >= 1e-4) return "HIGH";
        if (pc >= 1e-7) return "MEDIUM";
        return "LOW";
    }

    static double[][] rotateRTNtoInertial(double[][] covRTN, double[] posKm, double[] velKmS) {
        double[] rHat = normalize(posKm);
        double[] h = cross(posKm, velKmS);
        double[] nHat = normalize(h);
        double[] tHat = cross(nHat, rHat);
        double[][] M = new double[3][3];
        for (int i = 0; i < 3; i++) {
            M[i][0] = rHat[i];
            M[i][1] = tHat[i];
            M[i][2] = nHat[i];
        }
        double[][] temp = matMul3x3(M, covRTN);
        return matMul3x3T(temp, M);
    }

    static double[] sub(double[] a, double[] b) {
        return new double[]{a[0] - b[0], a[1] - b[1], a[2] - b[2]};
    }

    static double[] scale(double[] v, double s) {
        return new double[]{v[0] * s, v[1] * s, v[2] * s};
    }

    static double dot(double[] a, double[] b) {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    static double norm(double[] v) {
        return Math.sqrt(dot(v, v));
    }

    static double[] normalize(double[] v) {
        double n = norm(v);
        return new double[]{v[0] / n, v[1] / n, v[2] / n};
    }

    static double[] cross(double[] a, double[] b) {
        return new double[]{
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]
        };
    }

    static double quadForm(double[][] M, double[] u, double[] v) {
        double r = 0;
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                r += u[i] * M[i][j] * v[j];
        return r;
    }

    static double[][] matMul3x3(double[][] A, double[][] B) {
        double[][] C = new double[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                for (int k = 0; k < 3; k++)
                    C[i][j] += A[i][k] * B[k][j];
        return C;
    }

    static double[][] matMul3x3T(double[][] A, double[][] B) {
        double[][] C = new double[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                for (int k = 0; k < 3; k++)
                    C[i][j] += A[i][k] * B[j][k];
        return C;
    }

    static double[][] eigenVecs2x2(double[][] A, double lam1, double lam2) {
        double[][] V = new double[2][2];
        if (Math.abs(A[0][1]) < 1e-30) {
            V[0][0] = 1; V[1][0] = 0;
            V[0][1] = 0; V[1][1] = 1;
        } else {
            double vx = A[0][1];
            double vy = lam1 - A[0][0];
            double n = Math.sqrt(vx * vx + vy * vy);
            V[0][0] = vx / n; V[1][0] = vy / n;
            V[0][1] = -V[1][0]; V[1][1] = V[0][0];
        }
        return V;
    }

    public static class AnalysisResult {
        public final double collisionProbability;
        public final double relativeVelocityKmS;

        public AnalysisResult(double pc, double relVel) {
            this.collisionProbability = pc;
            this.relativeVelocityKmS = relVel;
        }
    }
}
