package tscodec

import (
	"fmt"
	"math/bits"
)

func marshalInt64NearestDelta(dst []byte, src []int64, precisionBits uint8) (result []byte, firstValue int64) {
	if len(src) < 1 {
		panic("src must contain at least 1 item")
	}
	if err := CheckPrecisionBits(precisionBits); err != nil {
		panic(err)
	}

	firstValue = src[0]
	v := src[0]
	src = src[1:]
	deltas := make([]int64, len(src))
	if precisionBits == 64 {
		for i, next := range src {
			d := next - v
			v += d
			deltas[i] = d
		}
	} else {
		trailingZeros := getTrailingZeros(v, precisionBits)
		for i, next := range src {
			d, tzs := nearestDelta(next, v, precisionBits, trailingZeros)
			trailingZeros = tzs
			v += d
			deltas[i] = d
		}
	}
	dst = MarshalVarInt64s(dst, deltas)
	return dst, firstValue
}

func unmarshalInt64NearestDelta(dst []int64, src []byte, firstValue int64, itemsCount int) ([]int64, error) {
	if itemsCount < 1 {
		panic("itemsCount must be >= 1")
	}

	deltas := make([]int64, itemsCount-1)
	tail, err := UnmarshalVarInt64s(deltas, src)
	if err != nil {
		return nil, fmt.Errorf("cannot unmarshal nearest delta: %w", err)
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

func nearestDelta(next, prev int64, precisionBits, prevTrailingZeros uint8) (int64, uint8) {
	d := next - prev
	if d == 0 {
		return 0, decIfNonZero(prevTrailingZeros)
	}

	origin := next
	if origin < 0 {
		origin = -origin
	}

	originBits := uint8(bits.Len64(uint64(origin)))
	if originBits <= precisionBits {
		return d, decIfNonZero(prevTrailingZeros)
	}

	trailingZeros := originBits - precisionBits
	if trailingZeros > prevTrailingZeros+4 {
		return d, prevTrailingZeros + 2
	}
	if trailingZeros+4 < prevTrailingZeros {
		return d, prevTrailingZeros - 2
	}

	minus := false
	if d < 0 {
		minus = true
		d = -d
	}
	nd := int64(uint64(d) & (uint64(1<<64-1) << trailingZeros))
	if minus {
		nd = -nd
	}
	return nd, trailingZeros
}

func decIfNonZero(n uint8) uint8 {
	if n == 0 {
		return 0
	}
	return n - 1
}

func getTrailingZeros(v int64, precisionBits uint8) uint8 {
	if v < 0 {
		v = -v
	}
	vBits := uint8(bits.Len64(uint64(v)))
	if vBits <= precisionBits {
		return 0
	}
	return vBits - precisionBits
}
