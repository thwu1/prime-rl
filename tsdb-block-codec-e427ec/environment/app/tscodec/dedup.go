package tscodec

// DeduplicateSamples removes samples closer than dedupInterval milliseconds.
func DeduplicateSamples(srcTimestamps []int64, srcValues []float64, dedupInterval int64) ([]int64, []float64) {
	if !needsDedup(srcTimestamps, dedupInterval) {
		return srcTimestamps, srcValues
	}
	tsNext := (srcTimestamps[0]/dedupInterval + 1) * dedupInterval
	dstTimestamps := srcTimestamps[:0]
	dstValues := srcValues[:0]
	for i, ts := range srcTimestamps[1:] {
		if ts <= tsNext {
			continue
		}
		j := i
		tsPrev := srcTimestamps[j]
		vPrev := srcValues[j]
		dstTimestamps = append(dstTimestamps, tsPrev)
		dstValues = append(dstValues, vPrev)
		tsNext += dedupInterval
	}
	j := len(srcTimestamps) - 1
	dstTimestamps = append(dstTimestamps, srcTimestamps[j])
	dstValues = append(dstValues, srcValues[j])
	return dstTimestamps, dstValues
}

func needsDedup(timestamps []int64, dedupInterval int64) bool {
	if len(timestamps) < 2 || dedupInterval <= 0 {
		return false
	}
	for i := 1; i < len(timestamps); i++ {
		if timestamps[i]-timestamps[i-1] < dedupInterval {
			return true
		}
	}
	return false
}
