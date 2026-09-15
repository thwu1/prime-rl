package gorillachunk

// bitRangeUint returns whether the given unsigned integer fits in nbits.
func bitRangeUint(x uint64, nbits int) bool {
	if nbits >= 64 {
		return true
	}
	return x < (1 << uint(nbits))
}

// putVarbitInt writes val using variable-width bit encoding.
//
// The encoding uses a unary prefix code to select a bit-width bucket,
// followed by the value encoded in that many bits using two's complement:
//
//	Prefix "0"        → val is exactly 0           (1 bit total)
//	Prefix "10"       → 3-bit signed value         (5 bits total, range: -3 to 4)
//	Prefix "110"      → 6-bit signed value         (9 bits total, range: -31 to 32)
//	Prefix "1110"     → 9-bit signed value         (13 bits total, range: -255 to 256)
//	Prefix "11110"    → 12-bit signed value        (17 bits total, range: -2047 to 2048)
//	Prefix "111110"   → 18-bit signed value        (24 bits total)
//	Prefix "1111110"  → 25-bit signed value        (32 bits total)
//	Prefix "11111110" → 56-bit signed value        (64 bits total)
//	Prefix "11111111" → 64-bit raw value           (72 bits total)
//
// Signed values use two's complement within the specified bit width.
// Use the bitRange helper from xor.go to determine the correct bucket.
func putVarbitInt(b *bstream, val int64) {
	panic("not implemented")
}

// readVarbitInt reads a value encoded by putVarbitInt.
//
// It reads the unary prefix to determine the bit-width bucket, then reads
// that many bits and converts from two's complement to a signed integer.
// For the conversion: if the unsigned value exceeds 1<<(sz-1), subtract 1<<sz
// to recover the negative value.
func readVarbitInt(b *bstreamReader) (int64, error) {
	panic("not implemented")
}

// putVarbitUint writes val using variable-width bit encoding.
//
// Same prefix scheme as putVarbitInt, but the value is an unsigned integer.
// The bit-width buckets are the same sizes (3, 6, 9, 12, 18, 25, 56, 64).
// Use the bitRangeUint helper to determine the correct bucket.
func putVarbitUint(b *bstream, val uint64) {
	panic("not implemented")
}

// readVarbitUint reads a value encoded by putVarbitUint.
//
// Same prefix decoding as readVarbitInt, but no sign extension is needed.
func readVarbitUint(b *bstreamReader) (uint64, error) {
	panic("not implemented")
}
