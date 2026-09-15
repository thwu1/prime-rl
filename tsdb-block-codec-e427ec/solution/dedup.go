package tscodec

// DeduplicateSamples removes samples closer than dedupInterval milliseconds.
// When multiple samples share a timestamp, the maximum value is kept,
// preferring non-StaleNaN values over StaleNaN.
func DeduplicateSamples(srcTimestamps []int64, srcValues []float64, dedupInterval int64) ([]int64, []float64) {
	if !needsDedup(srcTimestamps, dedupInterval) {
		return srcTimestamps, srcValues
	}
	tsNext := srcTimestamps[0] + dedupInterval - 1
	tsNext -= tsNext % dedupInterval
	dstTimestamps := srcTimestamps[:0]
	dstValues := srcValues[:0]
	for i, ts := range srcTimestamps[1:] {
		if ts <= tsNext {
			continue
		}
		j := i
		tsPrev := srcTimestamps[j]
		vPrev := srcValues[j]
		for j > 0 && srcTimestamps[j-1] == tsPrev {
			j--
			if IsStaleNaN(srcValues[j]) {
				continue
			}
			if IsStaleNaN(vPrev) {
				vPrev = srcValues[j]
				continue
			}
			if srcValues[j] > vPrev {
				vPrev = srcValues[j]
			}
		}
		dstTimestamps = append(dstTimestamps, tsPrev)
		dstValues = append(dstValues, vPrev)
		tsNext += dedupInterval
		if tsNext < ts {
			tsNext = ts + dedupInterval - 1
			tsNext -= tsNext % dedupInterval
		}
	}
	j := len(srcTimestamps) - 1
	tsPrev := srcTimestamps[j]
	vPrev := srcValues[j]
	for j > 0 && srcTimestamps[j-1] == tsPrev {
		j--
		if IsStaleNaN(srcValues[j]) {
			continue
		}
		if IsStaleNaN(vPrev) {
			vPrev = srcValues[j]
			continue
		}
		if srcValues[j] > vPrev {
			vPrev = srcValues[j]
		}
	}
	dstTimestamps = append(dstTimestamps, tsPrev)
	dstValues = append(dstValues, vPrev)
	return dstTimestamps, dstValues
}

func needsDedup(timestamps []int64, dedupInterval int64) bool {
	if len(timestamps) < 2 || dedupInterval <= 0 {
		return false
	}
	tsNext := timestamps[0] + dedupInterval - 1
	tsNext -= tsNext % dedupInterval
	for _, ts := range timestamps[1:] {
		if ts <= tsNext {
			return true
		}
		tsNext += dedupInterval
		if tsNext < ts {
			tsNext = ts + dedupInterval - 1
			tsNext -= tsNext % dedupInterval
		}
	}
	return false
}
