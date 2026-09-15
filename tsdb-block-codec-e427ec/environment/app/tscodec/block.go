package tscodec

import "fmt"

// Marshal appends the binary representation of bh to dst and returns the result.
func (bh *BlockHeader) Marshal(dst []byte) []byte {
	dst = MarshalVarInt64(dst, bh.MinTimestamp)
	dst = MarshalVarInt64(dst, bh.MaxTimestamp)
	dst = MarshalVarInt64(dst, bh.FirstValue)
	dst = MarshalVarUint64(dst, uint64(bh.RowsCount))
	dst = MarshalVarInt64(dst, int64(bh.Scale))
	dst = append(dst, byte(bh.TimestampsMarshalType), byte(bh.ValuesMarshalType), bh.PrecisionBits)
	return dst
}

// Unmarshal reads a BlockHeader from src and returns the remaining bytes.
func (bh *BlockHeader) Unmarshal(src []byte) ([]byte, error) {
	minTs, n := UnmarshalVarInt64(src)
	if n <= 0 {
		return src, fmt.Errorf("cannot unmarshal MinTimestamp")
	}
	src = src[n:]
	bh.MinTimestamp = minTs

	maxTs, n := UnmarshalVarInt64(src)
	if n <= 0 {
		return src, fmt.Errorf("cannot unmarshal MaxTimestamp")
	}
	src = src[n:]
	bh.MaxTimestamp = maxTs

	fv, n := UnmarshalVarInt64(src)
	if n <= 0 {
		return src, fmt.Errorf("cannot unmarshal FirstValue")
	}
	src = src[n:]
	bh.FirstValue = fv

	rc, n := UnmarshalVarUint64(src)
	if n <= 0 {
		return src, fmt.Errorf("cannot unmarshal RowsCount")
	}
	bh.RowsCount = uint32(rc)

	scale, n := UnmarshalVarInt64(src)
	if n <= 0 {
		return src, fmt.Errorf("cannot unmarshal Scale")
	}
	src = src[n:]
	bh.Scale = int16(scale)

	if len(src) < 3 {
		return src, fmt.Errorf("not enough bytes for trailing fields: need 3, have %d", len(src))
	}
	bh.TimestampsMarshalType = MarshalType(src[0])
	bh.ValuesMarshalType = MarshalType(src[1])
	bh.PrecisionBits = src[2]
	src = src[3:]

	return src, nil
}
