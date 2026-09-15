package main

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
)

// Wire type constants.
const (
	WireVarint     = 0
	WireFixed64    = 1
	WireLengthDelim = 2
	WireStartGroup = 3
	WireEndGroup   = 4
	WireFixed32    = 5
)

var (
	ErrTruncated   = errors.New("unexpected end of data")
	ErrOverflow    = errors.New("varint overflow")
	ErrInvalidWire = errors.New("invalid wire type")
	ErrBadGroup    = errors.New("mismatched group end marker")
)

// EncodeVarint encodes a uint64 as a protobuf base-128 varint.
func EncodeVarint(v uint64) []byte {
	var buf [10]byte
	n := 0
	for v >= 0x80 {
		buf[n] = byte(v) | 0x80
		v >>= 7
		n++
	}
	buf[n] = byte(v)
	return buf[:n+1]
}

// DecodeVarint decodes a varint from buf.
// Returns (value, bytesConsumed, error).
func DecodeVarint(buf []byte) (uint64, int, error) {
	var val uint64
	for i := 0; i < len(buf) && i < 10; i++ {
		b := buf[i]
		val |= uint64(b&0x7f) << (7 * uint(i))
		if b < 0x80 {
			return val, i + 1, nil
		}
	}
	if len(buf) >= 10 {
		return 0, 0, ErrOverflow
	}
	return 0, 0, ErrTruncated
}

// EncodeTag encodes a field number and wire type into a varint tag.
func EncodeTag(fieldNum uint32, wireType int) []byte {
	return EncodeVarint(uint64(fieldNum)<<3 | uint64(wireType))
}

// DecodeTag decodes a tag into field number and wire type.
func DecodeTag(buf []byte) (fieldNum uint32, wireType int, n int, err error) {
	v, n, err := DecodeVarint(buf)
	if err != nil {
		return 0, 0, 0, err
	}
	fieldNum = uint32(v >> 3)
	wireType = int(v & 0x7)
	if fieldNum == 0 {
		return 0, 0, 0, fmt.Errorf("invalid field number 0")
	}
	return fieldNum, wireType, n, nil
}

// EncodeZigZag encodes a signed int64 using ZigZag encoding.
func EncodeZigZag(n int64) uint64 {
	return uint64(n<<1) ^ uint64(n>>63)
}

// DecodeZigZag decodes a ZigZag-encoded uint64 back to int64.
func DecodeZigZag(n uint64) int64 {
	return int64(n>>1) ^ int64(n&1)
}

// EncodeFixed32 encodes a uint32 as 4 little-endian bytes.
func EncodeFixed32(v uint32) []byte {
	buf := make([]byte, 4)
	binary.LittleEndian.PutUint32(buf, v)
	return buf
}

// DecodeFixed32 decodes 4 little-endian bytes as a uint32.
func DecodeFixed32(buf []byte) (uint32, int, error) {
	if len(buf) < 4 {
		return 0, 0, ErrTruncated
	}
	return binary.LittleEndian.Uint32(buf), 4, nil
}

// EncodeFixed64 encodes a uint64 as 8 bytes.
func EncodeFixed64(v uint64) []byte {
	buf := make([]byte, 8)
	binary.BigEndian.PutUint64(buf, v)
	return buf
}

// DecodeFixed64 decodes 8 bytes as a uint64.
func DecodeFixed64(buf []byte) (uint64, int, error) {
	if len(buf) < 8 {
		return 0, 0, ErrTruncated
	}
	return binary.BigEndian.Uint64(buf), 8, nil
}

// EncodeFloat32 encodes a float32 as 4 little-endian bytes.
func EncodeFloat32(v float32) []byte {
	return EncodeFixed32(math.Float32bits(v))
}

// DecodeFloat32 decodes 4 bytes as a float32.
func DecodeFloat32(buf []byte) (float32, int, error) {
	v, n, err := DecodeFixed32(buf)
	if err != nil {
		return 0, 0, err
	}
	return math.Float32frombits(v), n, nil
}

// EncodeFloat64 encodes a float64 as 8 bytes.
func EncodeFloat64(v float64) []byte {
	return EncodeFixed64(math.Float64bits(v))
}

// DecodeFloat64 decodes 8 bytes as a float64.
func DecodeFloat64(buf []byte) (float64, int, error) {
	v, n, err := DecodeFixed64(buf)
	if err != nil {
		return 0, 0, err
	}
	return math.Float64frombits(v), n, nil
}

// DecodeBytes decodes a length-delimited byte slice.
func DecodeBytes(buf []byte) ([]byte, int, error) {
	length, n, err := DecodeVarint(buf)
	if err != nil {
		return nil, 0, err
	}
	if uint64(len(buf)-n) < length {
		return nil, 0, ErrTruncated
	}
	return buf[n : n+int(length)], n + int(length), nil
}

// EncodeBytes encodes a byte slice with a varint length prefix.
func EncodeBytes(v []byte) []byte {
	prefix := EncodeVarint(uint64(len(v)))
	return append(prefix, v...)
}
