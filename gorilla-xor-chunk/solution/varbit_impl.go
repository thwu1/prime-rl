package gorillachunk

import "fmt"

// bitRangeUint returns whether the given unsigned integer fits in nbits.
func bitRangeUint(x uint64, nbits int) bool {
	if nbits >= 64 {
		return true
	}
	return x < (1 << uint(nbits))
}

func putVarbitInt(b *bstream, val int64) {
	switch {
	case val == 0:
		b.writeBit(zero)
	case bitRange(val, 3):
		b.writeBits(0b10, 2)
		b.writeBits(uint64(val), 3)
	case bitRange(val, 6):
		b.writeBits(0b110, 3)
		b.writeBits(uint64(val), 6)
	case bitRange(val, 9):
		b.writeBits(0b1110, 4)
		b.writeBits(uint64(val), 9)
	case bitRange(val, 12):
		b.writeBits(0b11110, 5)
		b.writeBits(uint64(val), 12)
	case bitRange(val, 18):
		b.writeBits(0b111110, 6)
		b.writeBits(uint64(val), 18)
	case bitRange(val, 25):
		b.writeBits(0b1111110, 7)
		b.writeBits(uint64(val), 25)
	case bitRange(val, 56):
		b.writeBits(0b11111110, 8)
		b.writeBits(uint64(val), 56)
	default:
		b.writeBits(0b11111111, 8)
		b.writeBits(uint64(val), 64)
	}
}

func readVarbitInt(b *bstreamReader) (int64, error) {
	var d byte
	for i := 0; i < 8; i++ {
		d <<= 1
		bit, err := b.readBitFast()
		if err != nil {
			bit, err = b.readBit()
		}
		if err != nil {
			return 0, err
		}
		if bit == zero {
			break
		}
		d |= 1
	}

	var val int64
	var sz uint8

	switch d {
	case 0b0:
		// val == 0
	case 0b10:
		sz = 3
	case 0b110:
		sz = 6
	case 0b1110:
		sz = 9
	case 0b11110:
		sz = 12
	case 0b111110:
		sz = 18
	case 0b1111110:
		sz = 25
	case 0b11111110:
		sz = 56
	case 0b11111111:
		bits, err := b.readBits(64)
		if err != nil {
			return 0, err
		}
		val = int64(bits)
	default:
		return 0, fmt.Errorf("invalid varbit int prefix: %08b", d)
	}

	if sz != 0 {
		bits, err := b.readBitsFast(sz)
		if err != nil {
			bits, err = b.readBits(sz)
		}
		if err != nil {
			return 0, err
		}
		if bits > (1 << (sz - 1)) {
			bits -= (1 << sz)
		}
		val = int64(bits)
	}

	return val, nil
}

func putVarbitUint(b *bstream, val uint64) {
	switch {
	case val == 0:
		b.writeBit(zero)
	case bitRangeUint(val, 3):
		b.writeBits(0b10, 2)
		b.writeBits(val, 3)
	case bitRangeUint(val, 6):
		b.writeBits(0b110, 3)
		b.writeBits(val, 6)
	case bitRangeUint(val, 9):
		b.writeBits(0b1110, 4)
		b.writeBits(val, 9)
	case bitRangeUint(val, 12):
		b.writeBits(0b11110, 5)
		b.writeBits(val, 12)
	case bitRangeUint(val, 18):
		b.writeBits(0b111110, 6)
		b.writeBits(val, 18)
	case bitRangeUint(val, 25):
		b.writeBits(0b1111110, 7)
		b.writeBits(val, 25)
	case bitRangeUint(val, 56):
		b.writeBits(0b11111110, 8)
		b.writeBits(val, 56)
	default:
		b.writeBits(0b11111111, 8)
		b.writeBits(val, 64)
	}
}

func readVarbitUint(b *bstreamReader) (uint64, error) {
	var d byte
	for i := 0; i < 8; i++ {
		d <<= 1
		bit, err := b.readBitFast()
		if err != nil {
			bit, err = b.readBit()
		}
		if err != nil {
			return 0, err
		}
		if bit == zero {
			break
		}
		d |= 1
	}

	var (
		bits uint64
		sz   uint8
		err  error
	)

	switch d {
	case 0b0:
		// val == 0
	case 0b10:
		sz = 3
	case 0b110:
		sz = 6
	case 0b1110:
		sz = 9
	case 0b11110:
		sz = 12
	case 0b111110:
		sz = 18
	case 0b1111110:
		sz = 25
	case 0b11111110:
		sz = 56
	case 0b11111111:
		bits, err = b.readBits(64)
		if err != nil {
			return 0, err
		}
	default:
		return 0, fmt.Errorf("invalid varbit uint prefix: %08b", d)
	}

	if sz != 0 {
		bits, err = b.readBitsFast(sz)
		if err != nil {
			bits, err = b.readBits(sz)
		}
		if err != nil {
			return 0, err
		}
	}

	return bits, nil
}
