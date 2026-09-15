package gorillachunk

import (
	"encoding/binary"
	"io"
)

// bit represents a single bit value.
type bit bool

const (
	zero bit = false
	one  bit = true
)

// bstream is a stream of bits used for writing.
type bstream struct {
	stream []byte // The data stream.
	count  uint8  // How many right-most bits are available for writing in the current byte.
}

// Reset resets b around stream.
func (b *bstream) Reset(stream []byte) {
	b.stream = stream
	b.count = 0
}

func (b *bstream) bytes() []byte {
	return b.stream
}

func (b *bstream) writeBit(bit bit) {
	if b.count == 0 {
		b.stream = append(b.stream, 0)
		b.count = 8
	}

	i := len(b.stream) - 1

	if bit {
		b.stream[i] |= 1 << (b.count - 1)
	}

	b.count--
}

func (b *bstream) writeByte(byt byte) {
	if b.count == 0 {
		b.stream = append(b.stream, byt)
		return
	}

	i := len(b.stream) - 1

	// Complete the last byte with the leftmost b.count bits from byt.
	b.stream[i] |= byt >> (8 - b.count)

	// Write the remainder, if any.
	b.stream = append(b.stream, byt<<b.count)
}

// writeBits writes the nbits right-most bits of u to the stream
// in left-to-right order.
func (b *bstream) writeBits(u uint64, nbits int) {
	u <<= 64 - uint(nbits)
	for nbits >= 8 {
		byt := byte(u >> 56)
		b.writeByte(byt)
		u <<= 8
		nbits -= 8
	}

	for nbits > 0 {
		b.writeBit((u >> 63) == 1)
		u <<= 1
		nbits--
	}
}

// bstreamReader reads bits from a byte slice.
type bstreamReader struct {
	stream       []byte
	streamOffset int // The offset from which to read the next byte from the stream.

	buffer uint64 // The current buffer, filled from the stream, up to 8 bytes.
	valid  uint8  // The number of right-most bits valid to read (from left) in the current buffer.
	last   byte   // A copy of the last byte of the stream.
}

func newBReader(b []byte) bstreamReader {
	var last byte
	if len(b) > 0 {
		last = b[len(b)-1]
	}
	return bstreamReader{
		stream: b,
		last:   last,
	}
}

func (b *bstreamReader) readBit() (bit, error) {
	if b.valid == 0 {
		if !b.loadNextBuffer(1) {
			return false, io.EOF
		}
	}

	return b.readBitFast()
}

// readBitFast is like readBit but can return io.EOF if the internal buffer is empty.
// If it returns io.EOF, the caller should retry calling readBit().
func (b *bstreamReader) readBitFast() (bit, error) {
	if b.valid == 0 {
		return false, io.EOF
	}

	b.valid--
	bitmask := uint64(1) << b.valid
	return (b.buffer & bitmask) != 0, nil
}

// readBits constructs a uint64 with the nbits right-most bits
// read from the stream, and any other bits 0.
func (b *bstreamReader) readBits(nbits uint8) (uint64, error) {
	if b.valid == 0 {
		if !b.loadNextBuffer(nbits) {
			return 0, io.EOF
		}
	}

	if nbits <= b.valid {
		return b.readBitsFast(nbits)
	}

	// Read all remaining valid bits from the current buffer and a part from the next one.
	bitmask := (uint64(1) << b.valid) - 1
	nbits -= b.valid
	v := (b.buffer & bitmask) << nbits
	b.valid = 0

	if !b.loadNextBuffer(nbits) {
		return 0, io.EOF
	}

	bitmask = (uint64(1) << nbits) - 1
	v |= ((b.buffer >> (b.valid - nbits)) & bitmask)
	b.valid -= nbits

	return v, nil
}

// readBitsFast is like readBits but can return io.EOF if the internal buffer is empty.
// If it returns io.EOF, the caller should retry calling readBits().
func (b *bstreamReader) readBitsFast(nbits uint8) (uint64, error) {
	if nbits > b.valid {
		return 0, io.EOF
	}

	bitmask := (uint64(1) << nbits) - 1
	b.valid -= nbits

	return (b.buffer >> b.valid) & bitmask, nil
}

// ReadByte reads a single byte from the stream.
func (b *bstreamReader) ReadByte() (byte, error) {
	v, err := b.readBits(8)
	if err != nil {
		return 0, err
	}
	return byte(v), nil
}

// loadNextBuffer loads the next bytes from the stream into the internal buffer.
func (b *bstreamReader) loadNextBuffer(nbits uint8) bool {
	if b.streamOffset >= len(b.stream) {
		return false
	}

	// Handle the common case where more than 8 bytes remain.
	if b.streamOffset+8 < len(b.stream) {
		b.buffer = binary.BigEndian.Uint64(b.stream[b.streamOffset:])
		b.streamOffset += 8
		b.valid = 64
		return true
	}

	// Fewer than 8 bytes remain.
	nbytes := int((nbits / 8) + 1)
	if b.streamOffset+nbytes > len(b.stream) {
		nbytes = len(b.stream) - b.streamOffset
	}

	buffer := uint64(0)
	skip := 0
	if b.streamOffset+nbytes == len(b.stream) {
		// Use the copy of the last byte taken at initialization time.
		buffer |= uint64(b.last)
		skip = 1
	}

	for i := 0; i < nbytes-skip; i++ {
		buffer |= (uint64(b.stream[b.streamOffset+i]) << uint(8*(nbytes-i-1)))
	}

	b.buffer = buffer
	b.streamOffset += nbytes
	b.valid = uint8(nbytes * 8)

	return true
}
