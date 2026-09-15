package tscodec

import "fmt"

// MarshalVarInt64 encodes a signed int64 using zig-zag varint encoding
// and appends the result to dst.
func MarshalVarInt64(dst []byte, v int64) []byte {
	u := uint64((v << 1) ^ (v >> 63))
	return MarshalVarUint64(dst, u)
}

// UnmarshalVarInt64 decodes a zig-zag varint-encoded int64 from src.
// Returns the decoded value and the number of bytes consumed.
// Returns (0, 0) if src is too short.
func UnmarshalVarInt64(src []byte) (int64, int) {
	u, n := UnmarshalVarUint64(src)
	if n <= 0 {
		return 0, n
	}
	v := int64(u>>1) ^ (int64(u<<63) >> 63)
	return v, n
}

// MarshalVarInt64s encodes multiple signed int64 values.
func MarshalVarInt64s(dst []byte, vs []int64) []byte {
	for _, v := range vs {
		dst = MarshalVarInt64(dst, v)
	}
	return dst
}

// UnmarshalVarInt64s decodes len(dst) zig-zag varint-encoded int64 values from src.
func UnmarshalVarInt64s(dst []int64, src []byte) ([]byte, error) {
	for i := range dst {
		v, n := UnmarshalVarInt64(src)
		if n <= 0 {
			return nil, fmt.Errorf("cannot unmarshal varint at index %d from %d remaining bytes", i, len(src))
		}
		dst[i] = v
		src = src[n:]
	}
	return src, nil
}

// MarshalVarUint64 encodes an unsigned uint64 using varint encoding.
func MarshalVarUint64(dst []byte, u uint64) []byte {
	for u >= 0x80 {
		dst = append(dst, byte(u)|0x80)
		u >>= 7
	}
	dst = append(dst, byte(u))
	return dst
}

// UnmarshalVarUint64 decodes a varint-encoded uint64 from src.
func UnmarshalVarUint64(src []byte) (uint64, int) {
	if len(src) == 0 {
		return 0, 0
	}
	if src[0] < 0x80 {
		return uint64(src[0]), 1
	}
	var u uint64
	var shift uint
	for i, b := range src {
		if i >= 10 {
			return 0, -1
		}
		u |= uint64(b&0x7f) << shift
		if b < 0x80 {
			return u, i + 1
		}
		shift += 7
	}
	return 0, 0
}
