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
	v := src[0]
	src = src[1:]
	deltas := make([]int64, len(src))
	for i, next := range src {
		d := next - v
		v = next
		deltas[i] = d
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
	dst = append(dst, v)
	for _, d := range deltas {
		v += d
		dst = append(dst, v)
	}
	return dst, nil
}
