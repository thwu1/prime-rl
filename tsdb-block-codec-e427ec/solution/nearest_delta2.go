package tscodec

import "fmt"

func marshalInt64NearestDelta2(dst []byte, src []int64, precisionBits uint8) (result []byte, firstValue int64) {
	if len(src) < 2 {
		panic("src must contain at least 2 items")
	}
	if err := CheckPrecisionBits(precisionBits); err != nil {
		panic(err)
	}

	firstValue = src[0]
	d1 := src[1] - src[0]
	dst = MarshalVarInt64(dst, d1)
	v := src[1]
	src = src[2:]
	deltas := make([]int64, len(src))
	if precisionBits == 64 {
		for i, next := range src {
			d2 := next - v - d1
			d1 += d2
			v += d1
			deltas[i] = d2
		}
	} else {
		trailingZeros := getTrailingZeros(v, precisionBits)
		for i, next := range src {
			d2, tzs := nearestDelta(next-v, d1, precisionBits, trailingZeros)
			trailingZeros = tzs
			d1 += d2
			v += d1
			deltas[i] = d2
		}
	}
	dst = MarshalVarInt64s(dst, deltas)
	return dst, firstValue
}

func unmarshalInt64NearestDelta2(dst []int64, src []byte, firstValue int64, itemsCount int) ([]int64, error) {
	if itemsCount < 2 {
		panic("itemsCount must be >= 2")
	}

	deltas := make([]int64, itemsCount-1)
	tail, err := UnmarshalVarInt64s(deltas, src)
	if err != nil {
		return nil, fmt.Errorf("cannot unmarshal nearest delta2: %w", err)
	}
	if len(tail) > 0 {
		return nil, fmt.Errorf("unexpected %d trailing bytes", len(tail))
	}

	v := firstValue
	d1 := deltas[0]
	dst = append(dst, v)
	v += d1
	dst = append(dst, v)
	for _, d2 := range deltas[1:] {
		d1 += d2
		v += d1
		dst = append(dst, v)
	}
	return dst, nil
}
