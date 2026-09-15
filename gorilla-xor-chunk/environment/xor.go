package gorillachunk

import (
	"encoding/binary"
	"math"
	"math/bits"
)

const (
	chunkHeaderSize     = 2
	chunkAllocationSize = 128
)

// XORChunk holds XOR-encoded float sample data.
type XORChunk struct {
	b bstream
}

// NewXORChunk returns a new chunk with XOR encoding.
func NewXORChunk() *XORChunk {
	b := make([]byte, chunkHeaderSize, chunkAllocationSize)
	return &XORChunk{b: bstream{stream: b, count: 0}}
}

// Bytes returns the underlying byte slice of the chunk.
func (c *XORChunk) Bytes() []byte {
	return c.b.bytes()
}

// NumSamples returns the number of samples in the chunk.
func (c *XORChunk) NumSamples() int {
	return int(binary.BigEndian.Uint16(c.Bytes()))
}

// Compact optimizes the chunk's memory usage.
func (c *XORChunk) Compact() {
	if l := len(c.b.stream); cap(c.b.stream) > l+32 {
		buf := make([]byte, l)
		copy(buf, c.b.stream)
		c.b.stream = buf
	}
}

// Appender returns an appender to append samples to the chunk.
func (c *XORChunk) Appender() (Appender, error) {
	if len(c.b.stream) == chunkHeaderSize {
		return &xorAppender{b: &c.b, t: math.MinInt64, leading: 0xff}, nil
	}
	it := c.iterator(nil)
	for it.Next() != ValNone {
	}
	if err := it.Err(); err != nil {
		return nil, err
	}
	return &xorAppender{
		b:        &c.b,
		t:        it.t,
		v:        it.val,
		tDelta:   it.tDelta,
		leading:  it.leading,
		trailing: it.trailing,
	}, nil
}

func (c *XORChunk) iterator(it Iterator) *xorIterator {
	if xorIter, ok := it.(*xorIterator); ok {
		xorIter.Reset(c.b.bytes())
		return xorIter
	}
	return &xorIterator{
		br:       newBReader(c.b.bytes()[chunkHeaderSize:]),
		numTotal: binary.BigEndian.Uint16(c.b.bytes()),
		t:        math.MinInt64,
	}
}

// Iterator returns an iterator over the chunk's samples.
func (c *XORChunk) Iterator(it Iterator) Iterator {
	return c.iterator(it)
}

type xorAppender struct {
	b *bstream

	t      int64
	v      float64
	tDelta uint64

	leading  uint8
	trailing uint8
}

func (a *xorAppender) Append(t int64, v float64) {
	var tDelta uint64
	num := binary.BigEndian.Uint16(a.b.bytes())
	switch num {
	case 0:
		buf := make([]byte, binary.MaxVarintLen64)
		for _, b := range buf[:binary.PutVarint(buf, t)] {
			a.b.writeByte(b)
		}
		a.b.writeBits(math.Float64bits(v), 64)
	case 1:
		tDelta = uint64(t - a.t)

		buf := make([]byte, binary.MaxVarintLen64)
		for _, b := range buf[:binary.PutUvarint(buf, tDelta)] {
			a.b.writeByte(b)
		}

		a.writeVDelta(v)
	case math.MaxUint16:
		panic("chunk capacity exceeded")
	default:
		tDelta = uint64(t - a.t)
		dod := int64(tDelta - a.tDelta)

		switch {
		case dod == 0:
			a.b.writeBit(zero)
		case bitRange(dod, 14):
			a.b.writeByte(0b10<<6 | (uint8(dod>>8) & (1<<6 - 1)))
			a.b.writeByte(uint8(dod))
		case bitRange(dod, 17):
			a.b.writeBits(0b110, 3)
			a.b.writeBits(uint64(dod), 17)
		case bitRange(dod, 20):
			a.b.writeBits(0b1110, 4)
			a.b.writeBits(uint64(dod), 20)
		default:
			a.b.writeBits(0b1111, 4)
			a.b.writeBits(uint64(dod), 64)
		}

		a.writeVDelta(v)
	}

	a.t = t
	a.v = v
	binary.BigEndian.PutUint16(a.b.bytes(), num+1)
	a.tDelta = tDelta
}

// bitRange returns whether the given signed integer can be represented by nbits.
func bitRange(x int64, nbits uint8) bool {
	return -((1<<(nbits-1))-1) <= x && x <= 1<<(nbits-1)
}

func (a *xorAppender) writeVDelta(v float64) {
	xorWrite(a.b, v, a.v, &a.leading, &a.trailing)
}

func xorWrite(b *bstream, newValue, currentValue float64, leading, trailing *uint8) {
	delta := math.Float64bits(newValue) ^ math.Float64bits(currentValue)

	if delta == 0 {
		b.writeBit(zero)
		return
	}
	b.writeBit(one)

	newLeading := uint8(bits.LeadingZeros64(delta))
	newTrailing := uint8(bits.TrailingZeros64(delta))

	if *leading != 0xff && newLeading >= *leading && newTrailing >= *trailing {
		b.writeBit(zero)
		b.writeBits(delta>>*trailing, 64-int(*leading)-int(*trailing))
		return
	}

	*leading, *trailing = newLeading, newTrailing

	b.writeBit(one)
	b.writeBits(uint64(newLeading), 5)

	sigbits := 64 - newLeading - newTrailing
	b.writeBits(uint64(sigbits), 6)
	b.writeBits(delta>>newTrailing, int(sigbits))
}

type xorIterator struct {
	br       bstreamReader
	numTotal uint16
	numRead  uint16

	t   int64
	val float64

	leading  uint8
	trailing uint8

	tDelta uint64
	err    error
}

func (it *xorIterator) Seek(t int64) ValueType {
	if it.err != nil {
		return ValNone
	}

	for t > it.t || it.numRead == 0 {
		if it.Next() == ValNone {
			return ValNone
		}
	}
	return ValFloat
}

func (it *xorIterator) At() (int64, float64) {
	return it.t, it.val
}

func (it *xorIterator) Err() error {
	return it.err
}

func (it *xorIterator) Reset(b []byte) {
	it.br = newBReader(b[chunkHeaderSize:])
	it.numTotal = binary.BigEndian.Uint16(b)
	it.numRead = 0
	it.t = 0
	it.val = 0
	it.leading = 0
	it.trailing = 0
	it.tDelta = 0
	it.err = nil
}

func (it *xorIterator) Next() ValueType {
	if it.err != nil || it.numRead == it.numTotal {
		return ValNone
	}

	if it.numRead == 0 {
		t, err := binary.ReadVarint(&it.br)
		if err != nil {
			it.err = err
			return ValNone
		}
		v, err := it.br.readBits(64)
		if err != nil {
			it.err = err
			return ValNone
		}
		it.t = t
		it.val = math.Float64frombits(v)

		it.numRead++
		return ValFloat
	}
	if it.numRead == 1 {
		tDelta, err := binary.ReadUvarint(&it.br)
		if err != nil {
			it.err = err
			return ValNone
		}
		it.tDelta = tDelta
		it.t += int64(it.tDelta)

		return it.readValue()
	}

	var d byte
	// read delta-of-delta prefix
	for i := 0; i < 4; i++ {
		d <<= 1
		bit, err := it.br.readBitFast()
		if err != nil {
			bit, err = it.br.readBit()
		}
		if err != nil {
			it.err = err
			return ValNone
		}
		if bit == zero {
			break
		}
		d |= 1
	}
	var sz uint8
	var dod int64
	switch d {
	case 0b0:
		// dod == 0
	case 0b10:
		sz = 14
	case 0b110:
		sz = 17
	case 0b1110:
		sz = 20
	case 0b1111:
		readBits, err := it.br.readBits(64)
		if err != nil {
			it.err = err
			return ValNone
		}
		dod = int64(readBits)
	}

	if sz != 0 {
		readBits, err := it.br.readBitsFast(sz)
		if err != nil {
			readBits, err = it.br.readBits(sz)
		}
		if err != nil {
			it.err = err
			return ValNone
		}

		// Convert unsigned bits to signed value.
		if readBits >= (1 << (sz - 1)) {
			readBits -= 1 << sz
		}
		dod = int64(readBits)
	}

	it.tDelta = uint64(int64(it.tDelta) + dod)
	it.t += int64(it.tDelta)

	return it.readValue()
}

func (it *xorIterator) readValue() ValueType {
	err := xorRead(&it.br, &it.val, &it.leading, &it.trailing)
	if err != nil {
		it.err = err
		return ValNone
	}
	it.numRead++
	return ValFloat
}

func xorRead(br *bstreamReader, value *float64, leading, trailing *uint8) error {
	bit, err := br.readBitFast()
	if err != nil {
		bit, err = br.readBit()
	}
	if err != nil {
		return err
	}
	if bit == zero {
		return nil
	}
	bit, err = br.readBitFast()
	if err != nil {
		bit, err = br.readBit()
	}
	if err != nil {
		return err
	}

	var (
		readBits                       uint64
		newLeading, newTrailing, mbits uint8
	)

	if bit == zero {
		// Reuse leading/trailing zero bits.
		newLeading, newTrailing = *leading, *trailing
		mbits = 64 - newLeading - newTrailing
	} else {
		readBits, err = br.readBitsFast(5)
		if err != nil {
			readBits, err = br.readBits(5)
		}
		if err != nil {
			return err
		}
		newLeading = uint8(readBits)

		readBits, err = br.readBitsFast(6)
		if err != nil {
			readBits, err = br.readBits(6)
		}
		if err != nil {
			return err
		}
		mbits = uint8(readBits)
		newTrailing = 64 - newLeading - mbits
		*leading, *trailing = newLeading, newTrailing
	}
	readBits, err = br.readBitsFast(mbits)
	if err != nil {
		readBits, err = br.readBits(mbits)
	}
	if err != nil {
		return err
	}
	vbits := math.Float64bits(*value)
	vbits ^= readBits << newTrailing
	*value = math.Float64frombits(vbits)
	return nil
}
