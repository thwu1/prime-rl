package tscodec

import "fmt"

// MarshalValues marshals values with automatic encoding strategy selection.
func MarshalValues(dst []byte, values []int64, precisionBits uint8) (result []byte, mt MarshalType, firstValue int64) {
	if len(values) == 0 {
		panic("values must be non-empty")
	}

	if isConst(values) {
		return dst, MarshalTypeConst, values[0]
	}
	if isDeltaConst(values) {
		firstValue = values[0]
		dst = MarshalVarInt64(dst, values[1]-values[0])
		return dst, MarshalTypeDeltaConst, firstValue
	}

	if isGauge(values) {
		pb := precisionBits
		if pb < 6 {
			pb += 2
		}
		var fv int64
		dst, fv = marshalInt64NearestDelta(dst, values, pb)
		return dst, MarshalTypeNearestDelta, fv
	}

	var fv int64
	dst, fv = marshalInt64NearestDelta2(dst, values, precisionBits)
	return dst, MarshalTypeNearestDelta2, fv
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
	case MarshalTypeConst:
		if len(src) > 0 {
			return nil, fmt.Errorf("unexpected data for const encoding: %d bytes", len(src))
		}
		for i := 0; i < itemsCount; i++ {
			dst = append(dst, firstValue)
		}
		return dst, nil
	case MarshalTypeDeltaConst:
		d, n := UnmarshalVarInt64(src)
		if n <= 0 {
			return nil, fmt.Errorf("cannot unmarshal delta value for delta const")
		}
		if n < len(src) {
			return nil, fmt.Errorf("unexpected trailing data after delta const: %d bytes", len(src)-n)
		}
		v := firstValue
		for i := 0; i < itemsCount; i++ {
			dst = append(dst, v)
			v += d
		}
		return dst, nil
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
	if len(a) < 2 {
		return false
	}

	resets := 0
	vPrev := a[0]
	if vPrev < 0 {
		return true
	}
	for _, v := range a[1:] {
		if v < vPrev {
			if v < 0 {
				return true
			}
			if v > (vPrev >> 3) {
				return true
			}
			resets++
		}
		vPrev = v
	}
	if resets <= 2 {
		return false
	}
	return resets > (len(a) >> 3)
}
