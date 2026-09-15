
import java.util.Arrays;

/**
 * Complete HdrHistogram implementation.
 */
public class HdrHistogram {

    long lowestDiscernibleValue;
    long highestTrackableValue;
    int numberOfSignificantValueDigits;

    int unitMagnitude;
    long unitMagnitudeMask;
    int subBucketCount;
    int subBucketHalfCount;
    int subBucketHalfCountMagnitude;
    long subBucketMask;
    int leadingZeroCountBase;
    int bucketCount;
    int countsArrayLength;
    long[] counts;
    long totalCount;
    long maxValue;
    long minNonZeroValue;

    public HdrHistogram(long highestTrackableValue, int numberOfSignificantValueDigits) {
        this(1, highestTrackableValue, numberOfSignificantValueDigits);
    }

    public HdrHistogram(long lowestDiscernibleValue, long highestTrackableValue,
                         int numberOfSignificantValueDigits) {
        init(lowestDiscernibleValue, highestTrackableValue, numberOfSignificantValueDigits);
    }

    void init(long lowestDiscernibleValue, long highestTrackableValue,
              int numberOfSignificantValueDigits) {
        if (lowestDiscernibleValue < 1) {
            throw new IllegalArgumentException("lowestDiscernibleValue must be >= 1");
        }
        if (lowestDiscernibleValue > Long.MAX_VALUE / 2) {
            throw new IllegalArgumentException("lowestDiscernibleValue must be <= Long.MAX_VALUE / 2");
        }
        if (highestTrackableValue < 2L * lowestDiscernibleValue) {
            throw new IllegalArgumentException("highestTrackableValue must be >= 2 * lowestDiscernibleValue");
        }
        if (numberOfSignificantValueDigits < 0 || numberOfSignificantValueDigits > 5) {
            throw new IllegalArgumentException("numberOfSignificantValueDigits must be between 0 and 5");
        }

        this.lowestDiscernibleValue = lowestDiscernibleValue;
        this.highestTrackableValue = highestTrackableValue;
        this.numberOfSignificantValueDigits = numberOfSignificantValueDigits;

        final long largestValueWithSingleUnitResolution = 2 * (long) Math.pow(10, numberOfSignificantValueDigits);

        unitMagnitude = (int) (Math.log(lowestDiscernibleValue) / Math.log(2));
        unitMagnitudeMask = (1L << unitMagnitude) - 1;

        int subBucketCountMagnitude = (int) Math.ceil(Math.log(largestValueWithSingleUnitResolution) / Math.log(2));
        subBucketHalfCountMagnitude = subBucketCountMagnitude - 1;
        subBucketCount = 1 << subBucketCountMagnitude;
        subBucketHalfCount = subBucketCount / 2;
        subBucketMask = ((long) subBucketCount - 1) << unitMagnitude;

        if (subBucketCountMagnitude + unitMagnitude > 62) {
            throw new IllegalArgumentException(
                "Cannot represent numberOfSignificantValueDigits worth of values beyond lowestDiscernibleValue");
        }

        bucketCount = getBucketsNeededToCoverValue(highestTrackableValue);
        countsArrayLength = getLengthForNumberOfBuckets(bucketCount);
        leadingZeroCountBase = 64 - unitMagnitude - subBucketCountMagnitude;

        counts = new long[countsArrayLength];
        totalCount = 0;
        maxValue = 0;
        minNonZeroValue = Long.MAX_VALUE;
    }

    int getBucketIndex(long value) {
        return leadingZeroCountBase - Long.numberOfLeadingZeros(value | subBucketMask);
    }

    int getSubBucketIndex(long value, int bucketIndex) {
        return (int) (value >>> (bucketIndex + unitMagnitude));
    }

    int countsArrayIndex(long value) {
        if (value < 0) {
            throw new ArrayIndexOutOfBoundsException("Histogram recorded value cannot be negative.");
        }
        final int bucketIndex = getBucketIndex(value);
        final int subBucketIndex = getSubBucketIndex(value, bucketIndex);
        return countsArrayIndex(bucketIndex, subBucketIndex);
    }

    int countsArrayIndex(int bucketIndex, int subBucketIndex) {
        final int bucketBaseIndex = (bucketIndex + 1) << subBucketHalfCountMagnitude;
        final int offsetInBucket = subBucketIndex - subBucketHalfCount;
        return bucketBaseIndex + offsetInBucket;
    }

    long valueFromIndex(int index) {
        int bucketIndex = (index >> subBucketHalfCountMagnitude) - 1;
        int subBucketIndex = (index & (subBucketHalfCount - 1)) + subBucketHalfCount;
        if (bucketIndex < 0) {
            subBucketIndex -= subBucketHalfCount;
            bucketIndex = 0;
        }
        return valueFromIndex(bucketIndex, subBucketIndex);
    }

    long valueFromIndex(int bucketIndex, int subBucketIndex) {
        return ((long) subBucketIndex) << (bucketIndex + unitMagnitude);
    }

    int getBucketsNeededToCoverValue(long value) {
        long smallestUntrackableValue = ((long) subBucketCount) << unitMagnitude;
        int bucketsNeeded = 1;
        while (smallestUntrackableValue <= value) {
            if (smallestUntrackableValue > (Long.MAX_VALUE / 2)) {
                return bucketsNeeded + 1;
            }
            smallestUntrackableValue <<= 1;
            bucketsNeeded++;
        }
        return bucketsNeeded;
    }

    int getLengthForNumberOfBuckets(int numberOfBuckets) {
        return (numberOfBuckets + 1) * subBucketHalfCount;
    }

    private void updateMinAndMax(long value) {
        final long internalMaxValue = value | unitMagnitudeMask;
        if (internalMaxValue > maxValue) {
            maxValue = internalMaxValue;
        }
        if (value != 0 && value > unitMagnitudeMask) {
            final long internalMinValue = value & ~unitMagnitudeMask;
            if (internalMinValue < minNonZeroValue) {
                minNonZeroValue = internalMinValue;
            }
        }
    }

    public void recordValue(long value) {
        int idx = countsArrayIndex(value);
        if (idx < 0 || idx >= countsArrayLength) {
            throw new ArrayIndexOutOfBoundsException(
                "value " + value + " outside of histogram covered range");
        }
        counts[idx]++;
        updateMinAndMax(value);
        totalCount++;
    }

    public void recordValueWithCount(long value, long count) {
        int idx = countsArrayIndex(value);
        if (idx < 0 || idx >= countsArrayLength) {
            throw new ArrayIndexOutOfBoundsException(
                "value " + value + " outside of histogram covered range");
        }
        counts[idx] += count;
        updateMinAndMax(value);
        totalCount += count;
    }

    public void recordValueWithExpectedInterval(long value, long expectedIntervalBetweenValueSamples) {
        recordValue(value);
        if (expectedIntervalBetweenValueSamples <= 0) return;
        for (long missingValue = value - expectedIntervalBetweenValueSamples;
             missingValue >= expectedIntervalBetweenValueSamples;
             missingValue -= expectedIntervalBetweenValueSamples) {
            recordValue(missingValue);
        }
    }

    public long sizeOfEquivalentValueRange(long value) {
        final int bucketIndex = getBucketIndex(value);
        return 1L << (unitMagnitude + bucketIndex);
    }

    public long lowestEquivalentValue(long value) {
        final int bucketIndex = getBucketIndex(value);
        final int subBucketIndex = getSubBucketIndex(value, bucketIndex);
        return valueFromIndex(bucketIndex, subBucketIndex);
    }

    public long highestEquivalentValue(long value) {
        return nextNonEquivalentValue(value) - 1;
    }

    public long medianEquivalentValue(long value) {
        return lowestEquivalentValue(value) + (sizeOfEquivalentValueRange(value) >> 1);
    }

    public long nextNonEquivalentValue(long value) {
        return lowestEquivalentValue(value) + sizeOfEquivalentValueRange(value);
    }

    public boolean valuesAreEquivalent(long value1, long value2) {
        return lowestEquivalentValue(value1) == lowestEquivalentValue(value2);
    }

    public long getValueAtPercentile(double percentile) {
        double requestedPercentile =
            Math.min(Math.max(Math.nextAfter(percentile, Double.NEGATIVE_INFINITY), 0.0D), 100.0D);
        double fpCountAtPercentile = (requestedPercentile * getTotalCount()) / 100.0D;
        long countAtPercentile = (long) (Math.ceil(fpCountAtPercentile));
        countAtPercentile = Math.max(countAtPercentile, 1);
        long totalToCurrentIndex = 0;
        for (int i = 0; i < countsArrayLength; i++) {
            totalToCurrentIndex += counts[i];
            if (totalToCurrentIndex >= countAtPercentile) {
                long valueAtIndex = valueFromIndex(i);
                return (percentile == 0.0) ?
                    lowestEquivalentValue(valueAtIndex) :
                    highestEquivalentValue(valueAtIndex);
            }
        }
        return 0;
    }

    public double getPercentileAtOrBelowValue(long value) {
        if (getTotalCount() == 0) {
            return 100.0;
        }
        final int targetIndex = Math.min(countsArrayIndex(value), countsArrayLength - 1);
        long totalToCurrentIndex = 0;
        for (int i = 0; i <= targetIndex; i++) {
            totalToCurrentIndex += counts[i];
        }
        return (100.0 * totalToCurrentIndex) / getTotalCount();
    }

    public long getCountAtValue(long value) {
        final int index = Math.min(Math.max(0, countsArrayIndex(value)), countsArrayLength - 1);
        return counts[index];
    }

    public long getTotalCount() {
        return totalCount;
    }

    public long getMinValue() {
        if ((counts[0] > 0) || (getTotalCount() == 0)) {
            return 0;
        }
        return getMinNonZeroValue();
    }

    public long getMaxValue() {
        if (maxValue == 0) return 0;
        return highestEquivalentValue(maxValue);
    }

    public long getMinNonZeroValue() {
        if (minNonZeroValue == Long.MAX_VALUE) return Long.MAX_VALUE;
        return lowestEquivalentValue(minNonZeroValue);
    }

    public double getMean() {
        if (getTotalCount() == 0) return 0.0;
        double totalValue = 0;
        for (int i = 0; i < countsArrayLength; i++) {
            long countAtIdx = counts[i];
            if (countAtIdx > 0) {
                long valueAtIdx = valueFromIndex(i);
                totalValue += medianEquivalentValue(valueAtIdx) * (double) countAtIdx;
            }
        }
        return totalValue / getTotalCount();
    }

    public double getStdDeviation() {
        if (getTotalCount() == 0) return 0.0;
        final double mean = getMean();
        double geometricDeviationTotal = 0.0;
        for (int i = 0; i < countsArrayLength; i++) {
            long countAtIdx = counts[i];
            if (countAtIdx > 0) {
                long valueAtIdx = valueFromIndex(i);
                double deviation = (medianEquivalentValue(valueAtIdx) * 1.0) - mean;
                geometricDeviationTotal += (deviation * deviation) * countAtIdx;
            }
        }
        return Math.sqrt(geometricDeviationTotal / getTotalCount());
    }

    public int getEstimatedFootprintInBytes() {
        return 512 + (8 * counts.length);
    }

    public void add(HdrHistogram other) {
        long highestRecordableValue = highestEquivalentValue(valueFromIndex(countsArrayLength - 1));
        if (highestRecordableValue < other.getMaxValue()) {
            throw new ArrayIndexOutOfBoundsException(
                "The other histogram includes values that do not fit in this histogram's range.");
        }
        if (bucketCount == other.bucketCount &&
            subBucketCount == other.subBucketCount &&
            unitMagnitude == other.unitMagnitude) {
            long observedOtherTotalCount = 0;
            for (int i = 0; i < other.countsArrayLength; i++) {
                long otherCount = other.counts[i];
                if (otherCount > 0) {
                    counts[i] += otherCount;
                    observedOtherTotalCount += otherCount;
                }
            }
            totalCount += observedOtherTotalCount;
            long otherMaxVal = other.maxValue;
            if (otherMaxVal > maxValue) maxValue = otherMaxVal;
            long otherMinNZ = other.minNonZeroValue;
            if (otherMinNZ < minNonZeroValue) minNonZeroValue = otherMinNZ;
        } else {
            for (int i = 0; i < other.countsArrayLength; i++) {
                long otherCount = other.counts[i];
                if (otherCount > 0) {
                    recordValueWithCount(other.valueFromIndex(i), otherCount);
                }
            }
        }
    }

    public void subtract(HdrHistogram other) {
        long highestRecordableValue = highestEquivalentValue(valueFromIndex(countsArrayLength - 1));
        if (other.getMaxValue() > 0 && highestEquivalentValue(other.getMaxValue()) > highestRecordableValue) {
            throw new IllegalArgumentException(
                "The other histogram includes values that do not fit in this histogram's range.");
        }
        for (int i = 0; i < other.countsArrayLength; i++) {
            long otherCount = other.counts[i];
            if (otherCount > 0) {
                long otherValue = other.valueFromIndex(i);
                if (getCountAtValue(otherValue) < otherCount) {
                    throw new IllegalArgumentException("otherHistogram count (" + otherCount +
                        ") at value " + otherValue + " is larger than this one's (" +
                        getCountAtValue(otherValue) + ")");
                }
                int idx = countsArrayIndex(otherValue);
                counts[idx] -= otherCount;
                totalCount -= otherCount;
            }
        }
        // Recompute min/max
        reestablishInternalTrackingValues();
    }

    private void reestablishInternalTrackingValues() {
        maxValue = 0;
        minNonZeroValue = Long.MAX_VALUE;
        long observedTotalCount = 0;
        for (int i = countsArrayLength - 1; i >= 0; i--) {
            if (counts[i] > 0) {
                long val = valueFromIndex(i);
                updateMinAndMax(val);
                observedTotalCount += counts[i];
            }
        }
        // Also check from beginning for min
        for (int i = 0; i < countsArrayLength; i++) {
            if (counts[i] > 0) {
                long val = valueFromIndex(i);
                updateMinAndMax(val);
                break;
            }
        }
    }

    public void reset() {
        Arrays.fill(counts, 0);
        totalCount = 0;
        maxValue = 0;
        minNonZeroValue = Long.MAX_VALUE;
    }

    public long getLowestDiscernibleValue() { return lowestDiscernibleValue; }
    public long getHighestTrackableValue() { return highestTrackableValue; }
    public int getNumberOfSignificantValueDigits() { return numberOfSignificantValueDigits; }
}
