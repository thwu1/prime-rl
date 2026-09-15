import java.util.List;
import java.util.ArrayList;
import java.util.Collections;

/**
 * Feature extraction from raw triaxial acceleration measurements.
 *
 * San Diego features based on:
 *   Ellis K, Kerr J, Godbole S, Staudenmayer J, Lanckriet G.
 *   "Hip and Wrist Accelerometer Algorithms for Free-Living Behavior Classification"
 *
 * MAD features based on:
 *   Vaha-Ypya H, Vasankari T, Husu P, Suni J, Sievanen H.
 *   "A universal, accurate intensity-based classification of different physical
 *    activities using raw data of accelerometer"
 *
 * Arm angle features based on:
 *   van Hees VT et al.
 *   "Estimating sleep parameters using an accelerometer without sleep diary"
 *
 * Spectral features based on:
 *   Zhang S, Rowlands AV, Murray P, Hurst T.
 *   "Physical Activity Classification using the GENEA Wrist Worn Accelerometer"
 */
public class Features {

    public static double[] getFeatures(
            double[] x,
            double[] y,
            double[] z,
            int sampleRate) {

        // get San Diego (Ellis) features
        double[] sanDiegoFeats = calculateSanDiegoFeatures(x, y, z, sampleRate);

        // get MAD features
        double[] madFeats = calculateMADFeatures(x, y, z);

        // get arm angel features
        double[] armFeats = calculateArmFeatures(x, y, z, sampleRate);

        // get spectral features (DFT-based)
        double[] spectralFeats = calculateSpectralFeatures(x, y, z, sampleRate);

        // construct final output array
        double[] output = AccStats.combineArrays(sanDiegoFeats, madFeats);
        output = AccStats.combineArrays(output, armFeats);
        output = AccStats.combineArrays(output, spectralFeats);

        return output;
    }

    public static String getFeaturesHeader() {
        String header = getSanDiegoFeaturesHeader();
        header += "," + getMADFeaturesHeader();
        header += "," + getArmFeaturesHeader();
        header += "," + getSpectralFeaturesHeader();
        return header;
    }


    private static double[] calculateSanDiegoFeatures(
            double[] x, double[] y, double[] z, int sampleRate) {

        int n = x.length;

        // San Diego g values: the g matrix contains the estimated gravity vector
        // this is essentially a low pass filter
        double[] gg = sanDiegoGetAvgGravity(x, y, z, sampleRate);
        double gxMean = gg[0];
        double gyMean = gg[1];
        double gzMean = gg[2];

        // subtract column means and get vector magnitude
        double[] v = new double[n];
        double[] wx = new double[n];
        double[] wy = new double[n];
        double[] wz = new double[n];
        for (int i = 0; i < n; i++) {
            wx[i] = x[i] - gxMean;
            wy[i] = y[i] - gyMean;
            wz[i] = z[i] - gzMean;
            v[i] = AccStats.getVectorMagnitude(wx[i], wy[i], wz[i]);
        }

        // Write epoch
        double sdMean = AccStats.mean(v);
        double sdStd = AccStats.stdR(v, sdMean);
        double sdCoefVariation = 0.0;
        if (sdMean != 0) sdCoefVariation = sdStd / sdMean;
        double[] paQuartiles = AccStats.percentiles(v, new double[]{0, 0.25, 0.5, 0.75, 1});

        // correlations
        double autoCorrelation = correlation(v, v, sampleRate);
        double xyCorrelation = correlation(wx, wy);
        double xzCorrelation = correlation(wx, wz);
        double yzCorrelation = correlation(wy, wz);

        // Roll, Pitch, Yaw
        double[] angleAvgStdYZ = AccStats.angleAvgStd(wy, wz); // roll
        double[] angleAvgStdZX = AccStats.angleAvgStd(wz, wx); // pitch
        double[] angleAvgStdYX = AccStats.angleAvgStd(wy, wx); // yaw

        // gravity component angles
        double gxyAngle = Math.atan2(gyMean, gzMean);
        double gzxAngle = Math.atan2(gzMean, gxMean);
        double gyxAngle = Math.atan2(gyMean, gxMean);

        return new double[]{
            sdMean,
            sdStd,
            sdCoefVariation,
            paQuartiles[2], // median
            paQuartiles[0], // min
            paQuartiles[4], // max
            paQuartiles[1], // 25th
            paQuartiles[3], // 75th
            autoCorrelation,
            xyCorrelation,
            xzCorrelation,
            yzCorrelation,
            angleAvgStdYZ[0], // mean roll
            angleAvgStdZX[0], // mean pitch
            angleAvgStdYX[0], // mean yaw
            angleAvgStdYZ[1], // sd roll
            angleAvgStdZX[1], // sd pitch
            angleAvgStdYX[1], // sd yaw
            gxyAngle,
            gzxAngle,
            gyxAngle,
        };
    }

    private static String getSanDiegoFeaturesHeader() {
        String header = "mean,sd,coefvariation";
        header += ",median,min,max,25thp,75thp";
        header += ",autocorr,corrxy,corrxz,corryz";
        header += ",avgroll,avgpitch,avgyaw";
        header += ",sdroll,sdpitch,sdyaw";
        header += ",rollg,pitchg,yawg";
        return header;
    }


    // returns { x, y, z } averages of gravity
    private static double[] sanDiegoGetAvgGravity(
            double[] x, double[] y, double[] z, int sampleRate) {
        // San Diego paper low-pass filter approximation
        int n = x.length;
        int gn = n - (sampleRate - 1);
        int gStartIdx = n - gn;

        double[] gx = new double[gn];
        double[] gy = new double[gn];
        double[] gz = new double[gn];

        {
            // calculating moving average of signal
            double weight = 0.5;
            double xMovAvg = (1 - weight) * x[0];
            double yMovAvg = (1 - weight) * y[0];
            double zMovAvg = (1 - weight) * z[0];

            for (int i = 1; i < n; i++) {
                xMovAvg = xMovAvg * weight + (1 - weight) * x[i];
                yMovAvg = yMovAvg * weight + (1 - weight) * y[i];
                zMovAvg = zMovAvg * weight + (1 - weight) * z[i];
                if (i >= gStartIdx) {
                    gx[i - gStartIdx] = xMovAvg;
                    gy[i - gStartIdx] = yMovAvg;
                    gz[i - gStartIdx] = zMovAvg;
                }
            }
        }

        double gxMean = AccStats.mean(gx);
        double gyMean = AccStats.mean(gy);
        double gzMean = AccStats.mean(gz);

        return new double[]{gxMean, gyMean, gzMean};
    }


    /**
     * MAD features: Mean Amplitude Deviation, Mean Power Deviation,
     * Skewness, Kurtosis.
     */
    private static double[] calculateMADFeatures(
            double[] x, double[] y, double[] z) {

        double[] unfilteredVM = new double[x.length];
        for (int i = 0; i < x.length; i++) {
            if (!Double.isNaN(x[i])) {
                double vm = AccStats.getVectorMagnitude(x[i], y[i], z[i]);
                unfilteredVM[i] = vm - 1;
            }
        }

        // used in calculation
        int n = unfilteredVM.length;
        double N = (double) n;
        double vmMean = AccStats.mean(unfilteredVM);
        double vmStd = AccStats.std(unfilteredVM, vmMean);

        // features from paper:
        double MAD = 0;
        double MPD = 0;
        double skew = 0;
        double kurt = 0;
        for (int i = 0; i < n; i++) {
            double diff = unfilteredVM[i] - vmMean;
            MAD += Math.abs(diff);
            MPD += Math.pow(Math.abs(diff), 2.0);
            skew += Math.pow(diff / (vmStd + 1E-8), 3);
            kurt += Math.pow(diff / (vmStd + 1E-8), 4);
        }

        MAD /= N;
        MPD /= Math.pow(N, 1.5);
        skew *= N / ((N - 1) * (N - 2));
        kurt = kurt / N - 3.0;

        return new double[]{
            MAD,
            MPD,
            skew,
            kurt
        };
    }

    private static String getMADFeaturesHeader() {
        return "MAD,MPD,skew,kurt";
    }


    /**
     * Arm angle features for sleep estimation.
     */
    private static double[] calculateArmFeatures(
            double[] x, double[] y, double[] z, int sampleRate) {
        int window_len = 5; // 5-sec
        if (x.length / sampleRate < window_len) {
            return new double[]{0, 0};
        } else {
            // 1. 5-sec rolling medians
            int k = window_len * sampleRate;
            double[] rollingMedianX = medianSlidingWindow(x, k);
            double[] rollingMedianY = medianSlidingWindow(y, k);
            double[] rollingMedianZ = medianSlidingWindow(z, k);

            // 2. compute arm angle
            double[] angelZ = new double[rollingMedianX.length];

            for (int i = 0; i < rollingMedianX.length; i++) {
                double tmp = rollingMedianZ[i]
                        / (Math.pow(rollingMedianX[i], 2)
                        + Math.pow(rollingMedianY[i], 2));
                angelZ[i] = Math.atan(tmp) * 180 / Math.PI;
            }

            // 3. consecutive 5-sec avg
            double[] fiveSecAvg = computeFiveSecAvg(angelZ, sampleRate);
            double avgArmAngel = AccStats.mean(fiveSecAvg);

            // 4. Absolute difference between successive values
            double avgArmAngelAbsDiff = 0;
            if (x.length / sampleRate >= 10) {
                double[] absoluteAvgDiff = computeAbsoluteDiff(fiveSecAvg);
                avgArmAngelAbsDiff = AccStats.mean(absoluteAvgDiff);
            }

            return new double[]{
                avgArmAngel,
                avgArmAngelAbsDiff
            };
        }
    }

    private static String getArmFeaturesHeader() {
        return "avgArmAngel,avgArmAngelAbsDiff";
    }


    /**
     * DFT-based spectral features of the gravity-subtracted
     * vector magnitude signal: dominant frequency and spectral entropy.
     */
    private static double[] calculateSpectralFeatures(
            double[] x, double[] y, double[] z, int sampleRate) {

        int n = x.length;

        // Gravity estimation (same method as San Diego features)
        double[] gg = sanDiegoGetAvgGravity(x, y, z, sampleRate);

        // Gravity-subtracted vector magnitude
        double[] v = new double[n];
        for (int i = 0; i < n; i++) {
            v[i] = AccStats.getVectorMagnitude(
                    x[i] - gg[0], y[i] - gg[1], z[i] - gg[2]);
        }

        double vMean = AccStats.mean(v);

        // Remove DC component and prepare for DFT
        double[] windowed = new double[n];
        for (int i = 0; i < n; i++) {
            windowed[i] = v[i] - vMean;
        }

        // Compute one-sided DFT power spectrum
        int numBins = n / 2 + 1;
        double[] power = new double[numBins];
        for (int k = 0; k < numBins; k++) {
            double re = 0, im = 0;
            for (int i = 0; i < n; i++) {
                double angle = 2.0 * Math.PI * k * i / n;
                re += windowed[i] * Math.cos(angle);
                im -= windowed[i] * Math.sin(angle);
            }
            power[k] = (re * re + im * im) / ((double) n * n);
        }

        // Find dominant frequency (skip DC bin at k=0)
        double freqRes = (double) sampleRate / n;
        double fmax = 0;
        double pmax = 0;
        for (int k = 1; k < numBins; k++) {
            if (power[k] > pmax) {
                pmax = power[k];
                fmax = k * freqRes;
            }
        }
        pmax = Math.log(pmax + 1e-8);

        // Spectral entropy (normalized)
        double totalPower = 0;
        for (int k = 1; k < numBins; k++) {
            totalPower += power[k];
        }
        double entropy = 0;
        for (int k = 1; k < numBins; k++) {
            double p = power[k] / (totalPower + 1e-8);
            if (p > 0) {
                entropy += -p * Math.log(p + 1e-8);
            }
        }
        entropy /= Math.log(numBins - 1);

        return new double[]{fmax, pmax, entropy};
    }

    private static String getSpectralFeaturesHeader() {
        return "fmax,pmax,entropy";
    }


    /**
     * Obtain the rolling window median of window of size k.
     */
    public static double[] medianSlidingWindow(double[] nums, int k) {
        double[] res = new double[nums.length - k + 1];
        List<Double> list = new ArrayList<Double>();
        for (int i = 0; i < k; i++) {
            list.add(nums[i]);
        }
        Collections.sort(list);
        res[0] = (k % 2 == 0)
                ? ((double) list.get(k / 2 - 1) + (double) list.get(k / 2)) / 2
                : list.get(k / 2);
        for (int i = 0; i < nums.length - k; i++) {
            double left = nums[i];
            double right = nums[i + k];
            int index = Collections.binarySearch(list, right);
            if (index >= 0) list.add(index, right);
            else list.add(-index - 1, right);
            index = Collections.binarySearch(list, left);
            list.remove(index);
            res[i + 1] = (k % 2 == 0)
                    ? ((double) list.get(k / 2 - 1) + (double) list.get(k / 2)) / 2
                    : list.get(k / 2);
        }
        return res;
    }

    private static double[] computeFiveSecAvg(double[] x, int sampleRate) {
        int avgsLen = (int) Math.ceil(x.length / (5.0 * sampleRate));
        double[] avgs = new double[avgsLen];
        int count = 0;
        double sum = 0;
        int j = 0;
        for (int i = 0; i < x.length; i++) {
            count++;
            sum += x[i];
            if (count == 5 * sampleRate || i == x.length - 1) {
                avgs[j] = sum / count;
                j++;
                sum = 0;
                count = 0;
            }
        }
        return avgs;
    }

    private static double[] computeAbsoluteDiff(double[] x) {
        double[] res = new double[x.length - 1];
        for (int i = 1; i < x.length; i++) {
            res[i - 1] = Math.abs(x[i] - x[i - 1]);
        }
        return res;
    }


    /**
     * Correlation wrapper that returns 0.0 for non-finite results.
     */
    private static double correlation(double[] vals1, double[] vals2, int lag) {
        double res = AccStats.correlation(vals1, vals2, lag);
        if (!Double.isFinite(res)) return 0.0;
        return res;
    }

    private static double correlation(double[] vals1, double[] vals2) {
        return correlation(vals1, vals2, 0);
    }
}
