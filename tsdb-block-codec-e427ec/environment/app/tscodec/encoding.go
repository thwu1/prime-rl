package tscodec

import "fmt"

// MarshalValues marshals values with automatic encoding strategy selection.
func MarshalValues(dst []byte, values []int64, precisionBits uint8) (result []byte, mt MarshalType, firstValue int64) {
	if len(values) == 0 {
		panic("values must be non-empty")
	}

	if len(values) >= 2 {
		var fv int64
		dst, fv = marshalInt64NearestDelta2(dst, values, precisionBits)
		return dst, MarshalTypeNearestDelta2, fv
	}

	return dst, MarshalTypeConst, values[0]
}

// MarshalTimestamps marshals timestamps with automatic encoding strategy selection.
func MarshalTimestamps(dst []byte, timestamps []int64, precisionBits uint8) (result []byte, mt MarshalType, firstTimestamp int64) {
	return MarshalValues(dst, timestamps, precisionBits)
}

// UnmarshalValues unmarshals values encoded with the given MarshalType.
func UnmarshalValues(dst []int64, src []byte, mt MarshalType, firstValue int64, itemsCount int) ([]int64, error) {
	switch mt {
	case MarshalTypeNearestDelta, MarshalTypeZSTDNearestDelta:
		return unmarshalInt64NearestDelta(dst, src, firstValue, itemsCount)
	case MarshalTypeNearestDelta2, MarshalTypeZSTDNearestDelta2:
		return unmarshalInt64NearestDelta2(dst, src, firstValue, itemsCount)
	default:
		return nil, fmt.Errorf("unsupported MarshalType: %d", mt)
	}
}

// UnmarshalTimestamps unmarshals timestamps encoded with the given MarshalType.
func UnmarshalTimestamps(dst []int64, src []byte, mt MarshalType, firstTimestamp int64, itemsCount int) ([]int64, error) {
	return UnmarshalValues(dst, src, mt, firstTimestamp, itemsCount)
}

func isConst(a []int64) bool {
	if len(a) == 0 {
		return false
	}
	v := a[0]
	for _, x := range a[1:] {
		if x != v {
			return false
		}
	}
	return true
}

func isDeltaConst(a []int64) bool {
	if len(a) < 2 {
		return false
	}
	d := a[1] - a[0]
	for i := 2; i < len(a); i++ {
		if a[i]-a[i-1] != d {
			return false
		}
	}
	return true
}

func isGauge(a []int64) bool {
	return false
}
