package tscodec


import (
	"bytes"
	"fmt"
	"math"
	"reflect"
	"testing"
)

// --- Varint Tests ---

func TestVarIntRoundTrip(t *testing.T) {
	testCases := []int64{
		0, 1, -1, 2, -2, 63, -64, 64, -65, 127, -128,
		1000, -1000, 100000, -100000,
		1 << 20, -(1 << 20), 1 << 40, -(1 << 40),
		math.MaxInt64, math.MinInt64, math.MaxInt64 / 2, math.MinInt64 / 2,
	}
	for _, v := range testCases {
		buf := MarshalVarInt64(nil, v)
		decoded, n := UnmarshalVarInt64(buf)
		if n != len(buf) {
			t.Fatalf("UnmarshalVarInt64(%d): consumed %d bytes, buf has %d", v, n, len(buf))
		}
		if decoded != v {
			t.Fatalf("VarInt64 round-trip failed for %d: got %d", v, decoded)
		}
	}
}

func TestVarUintRoundTrip(t *testing.T) {
	testCases := []uint64{
		0, 1, 127, 128, 255, 256, 16383, 16384,
		1 << 21, 1 << 28, 1 << 35, 1 << 49, 1 << 56, 1 << 63,
		math.MaxUint64,
	}
	for _, u := range testCases {
		buf := MarshalVarUint64(nil, u)
		decoded, n := UnmarshalVarUint64(buf)
		if n != len(buf) {
			t.Fatalf("UnmarshalVarUint64(%d): consumed %d bytes, buf has %d", u, n, len(buf))
		}
		if decoded != u {
			t.Fatalf("VarUint64 round-trip failed for %d: got %d", u, decoded)
		}
	}
}

func TestVarIntByteOutput(t *testing.T) {
	tests := []struct {
		v    int64
		want []byte
	}{
		{0, []byte{0x00}},
		{1, []byte{0x02}},
		{-1, []byte{0x01}},
		{-2, []byte{0x03}},
		{2, []byte{0x04}},
	}
	for _, tt := range tests {
		got := MarshalVarInt64(nil, tt.v)
		if !bytes.Equal(got, tt.want) {
			t.Fatalf("MarshalVarInt64(%d): got %x, want %x", tt.v, got, tt.want)
		}
	}
}

func TestVarInt64sRoundTrip(t *testing.T) {
	values := []int64{0, 1, -1, 100, -100, 10000, -10000, math.MaxInt64, math.MinInt64}
	buf := MarshalVarInt64s(nil, values)
	decoded := make([]int64, len(values))
	tail, err := UnmarshalVarInt64s(decoded, buf)
	if err != nil {
		t.Fatal(err)
	}
	if len(tail) != 0 {
		t.Fatalf("unexpected tail: %d bytes", len(tail))
	}
	if !reflect.DeepEqual(decoded, values) {
		t.Fatalf("VarInt64s round-trip failed:\ngot  %v\nwant %v", decoded, values)
	}
}

// --- NearestDelta Tests ---

func TestNearestDeltaByteExact(t *testing.T) {
	tests := []struct {
		src           []int64
		precisionBits uint8
		firstValue    int64
		wantHex       string
	}{
		{[]int64{0}, 4, 0, ""},
		{[]int64{0, 0}, 4, 0, "00"},
		{[]int64{1, -3}, 4, 1, "07"},
		{[]int64{255, 255}, 4, 255, "00"},
		{[]int64{0, 1, 2, 3, 4, 5}, 4, 0, "0202020202"},
		{[]int64{5, 4, 3, 2, 1, 0}, 1, 5, "0003000301"},
		{[]int64{5, 4, 3, 2, 1, 0}, 4, 5, "0101010101"},
	}
	for _, tt := range tests {
		b, fv := marshalInt64NearestDelta(nil, tt.src, tt.precisionBits)
		if fv != tt.firstValue {
			t.Fatalf("marshalInt64NearestDelta(%v, %d): firstValue = %d, want %d",
				tt.src, tt.precisionBits, fv, tt.firstValue)
		}
		gotHex := ""
		for _, c := range b {
			gotHex += fmt.Sprintf("%02x", c)
		}
		if gotHex != tt.wantHex {
			t.Fatalf("marshalInt64NearestDelta(%v, %d): bytes = %s, want %s",
				tt.src, tt.precisionBits, gotHex, tt.wantHex)
		}
	}
}

func TestNearestDeltaRoundTrip(t *testing.T) {
	tests := []struct {
		src           []int64
		precisionBits uint8
	}{
		{[]int64{0}, 64},
		{[]int64{0, 0}, 64},
		{[]int64{1, -3}, 64},
		{[]int64{0, 1, 2, 3, 4, 5}, 64},
		{[]int64{5, 4, 3, 2, 1, 0}, 64},
		{[]int64{100, 200, 300, 400, 500}, 64},
		{[]int64{-100, -200, -300, -400}, 64},
		{[]int64{1000, 999, 1001, 998, 1002}, 64},
	}
	for _, tt := range tests {
		b, fv := marshalInt64NearestDelta(nil, tt.src, tt.precisionBits)
		decoded, err := unmarshalInt64NearestDelta(nil, b, fv, len(tt.src))
		if err != nil {
			t.Fatalf("unmarshalInt64NearestDelta error for %v: %v", tt.src, err)
		}
		if !reflect.DeepEqual(decoded, tt.src) {
			t.Fatalf("NearestDelta round-trip (pb=%d) failed:\nsrc     = %v\ndecoded = %v",
				tt.precisionBits, tt.src, decoded)
		}
	}
}

func TestNearestDeltaPrecisionRoundTrip(t *testing.T) {
	// With precision bits < 64, values may be lossy but round-trip must be self-consistent
	src := []int64{1000, 1100, 1200, 1050, 1300, 950, 1400}
	for _, pb := range []uint8{1, 2, 4, 8, 16, 32, 64} {
		b, fv := marshalInt64NearestDelta(nil, src, pb)
		decoded, err := unmarshalInt64NearestDelta(nil, b, fv, len(src))
		if err != nil {
			t.Fatalf("unmarshal error for pb=%d: %v", pb, err)
		}
		if len(decoded) != len(src) {
			t.Fatalf("pb=%d: length mismatch: got %d, want %d", pb, len(decoded), len(src))
		}
		// Re-encode the decoded values: should produce identical bytes (idempotent)
		b2, fv2 := marshalInt64NearestDelta(nil, decoded, pb)
		if fv2 != fv {
			t.Fatalf("pb=%d: re-encode firstValue mismatch: %d vs %d", pb, fv2, fv)
		}
		if !bytes.Equal(b2, b) {
			t.Fatalf("pb=%d: re-encode bytes mismatch:\nfirst  = %x\nsecond = %x", pb, b, b2)
		}
	}
}

// --- NearestDelta2 Tests ---

func TestNearestDelta2ByteExact(t *testing.T) {
	// Linear data [0, 10, 20, 30] with lossless encoding:
	// d1 = 10 (varint prefix), d2 = [0, 0] (zero second-order deltas)
	// Expected: MarshalVarInt64(10) ++ MarshalVarInt64s([0, 0]) = [0x14, 0x00, 0x00]
	src := []int64{0, 10, 20, 30}
	b, fv := marshalInt64NearestDelta2(nil, src, 64)
	if fv != 0 {
		t.Fatalf("expected firstValue=0, got %d", fv)
	}
	expected := []byte{0x14, 0x00, 0x00}
	if !bytes.Equal(b, expected) {
		t.Fatalf("marshalInt64NearestDelta2 bytes: got %x, want %x", b, expected)
	}
}

func TestNearestDelta2ByteExactQuadratic(t *testing.T) {
	// Quadratic data [0, 10, 30, 60] (deltas: 10, 20, 30; d2: 10, 10)
	// d1 = 10 (varint), d2 = [10, 10]
	// Expected: [0x14] ++ MarshalVarInt64s([10, 10]) = [0x14, 0x14, 0x14]
	src := []int64{0, 10, 30, 60}
	b, fv := marshalInt64NearestDelta2(nil, src, 64)
	if fv != 0 {
		t.Fatalf("expected firstValue=0, got %d", fv)
	}
	expected := []byte{0x14, 0x14, 0x14}
	if !bytes.Equal(b, expected) {
		t.Fatalf("marshalInt64NearestDelta2 bytes: got %x, want %x", b, expected)
	}
}

func TestNearestDelta2UnmarshalKnown(t *testing.T) {
	// Unmarshal correctly-encoded bytes for [0, 10, 20, 30]
	b := []byte{0x14, 0x00, 0x00}
	decoded, err := unmarshalInt64NearestDelta2(nil, b, 0, 4)
	if err != nil {
		t.Fatal(err)
	}
	expected := []int64{0, 10, 20, 30}
	if !reflect.DeepEqual(decoded, expected) {
		t.Fatalf("got %v, want %v", decoded, expected)
	}
}

func TestNearestDelta2RoundTrip(t *testing.T) {
	tests := []struct {
		src           []int64
		precisionBits uint8
	}{
		{[]int64{0, 10}, 64},
		{[]int64{0, 10, 20, 30}, 64},
		{[]int64{0, 10, 30, 60, 100}, 64},
		{[]int64{100, 200, 300, 400, 500}, 64},
		{[]int64{0, 1, 4, 9, 16, 25, 36}, 64},
		{[]int64{1000, 1010, 1030, 1060, 1100}, 64},
	}
	for _, tt := range tests {
		b, fv := marshalInt64NearestDelta2(nil, tt.src, tt.precisionBits)
		decoded, err := unmarshalInt64NearestDelta2(nil, b, fv, len(tt.src))
		if err != nil {
			t.Fatalf("unmarshal error for %v: %v", tt.src, err)
		}
		if !reflect.DeepEqual(decoded, tt.src) {
			t.Fatalf("NearestDelta2 round-trip failed:\nsrc     = %v\ndecoded = %v", tt.src, decoded)
		}
	}
}

// --- Encoding Strategy Tests ---

func TestIsConst(t *testing.T) {
	if !isConst([]int64{42, 42, 42, 42}) {
		t.Fatal("expected true for constant values")
	}
	if isConst([]int64{42, 42, 43}) {
		t.Fatal("expected false for non-constant values")
	}
	if !isConst([]int64{0, 0, 0}) {
		t.Fatal("expected true for zeros")
	}
}

func TestIsDeltaConst(t *testing.T) {
	if !isDeltaConst([]int64{0, 10, 20, 30, 40}) {
		t.Fatal("expected true for constant delta")
	}
	if isDeltaConst([]int64{0, 10, 20, 31}) {
		t.Fatal("expected false for non-constant delta")
	}
	if isDeltaConst([]int64{5}) {
		t.Fatal("expected false for single element")
	}
}

func TestIsGauge(t *testing.T) {
	// Gauge: values go up and down, with small decreases
	if !isGauge([]int64{100, 95, 105, 90, 110, 85, 115}) {
		t.Fatal("expected true for gauge-like data")
	}
	// Gauge: negative values
	if !isGauge([]int64{-5, -3, -1, 0, 1, 3}) {
		t.Fatal("expected true for data with negative values")
	}
	// Counter: monotonically increasing, no resets
	if isGauge([]int64{0, 10, 20, 30, 40, 50, 60}) {
		t.Fatal("expected false for monotonically increasing counter")
	}
	// Counter with full reset (drops near zero)
	if isGauge([]int64{0, 100, 200, 300, 0, 100, 200}) {
		t.Fatal("expected false for counter with reset to zero")
	}
}

func TestMarshalValuesConst(t *testing.T) {
	values := []int64{42, 42, 42, 42, 42}
	b, mt, fv := MarshalValues(nil, values, 64)
	if mt != MarshalTypeConst {
		t.Fatalf("expected MarshalTypeConst (%d), got %d", MarshalTypeConst, mt)
	}
	if fv != 42 {
		t.Fatalf("expected firstValue=42, got %d", fv)
	}
	if len(b) != 0 {
		t.Fatalf("expected empty bytes for const, got %d bytes", len(b))
	}
}

func TestMarshalValuesDeltaConst(t *testing.T) {
	values := []int64{0, 10, 20, 30, 40}
	b, mt, fv := MarshalValues(nil, values, 64)
	if mt != MarshalTypeDeltaConst {
		t.Fatalf("expected MarshalTypeDeltaConst (%d), got %d", MarshalTypeDeltaConst, mt)
	}
	if fv != 0 {
		t.Fatalf("expected firstValue=0, got %d", fv)
	}
	d, n := UnmarshalVarInt64(b)
	if d != 10 || n != len(b) {
		t.Fatalf("expected delta=10, got %d (consumed %d of %d bytes)", d, n, len(b))
	}
}

func TestMarshalValuesGauge(t *testing.T) {
	values := []int64{100, 95, 105, 90, 110, 85, 115}
	_, mt, _ := MarshalValues(nil, values, 64)
	if mt != MarshalTypeNearestDelta {
		t.Fatalf("expected MarshalTypeNearestDelta (%d), got %d", MarshalTypeNearestDelta, mt)
	}
}

func TestMarshalValuesCounter(t *testing.T) {
	// Non-const, non-deltaConst, non-gauge → counter → NearestDelta2
	values := []int64{0, 10, 20, 30, 41, 50, 60}
	_, mt, _ := MarshalValues(nil, values, 64)
	if mt != MarshalTypeNearestDelta2 {
		t.Fatalf("expected MarshalTypeNearestDelta2 (%d), got %d", MarshalTypeNearestDelta2, mt)
	}
}

func TestMarshalUnmarshalValuesRoundTrip(t *testing.T) {
	testCases := []struct {
		name          string
		values        []int64
		precisionBits uint8
	}{
		{"const", []int64{42, 42, 42, 42, 42}, 64},
		{"const_zero", []int64{0, 0, 0, 0}, 64},
		{"delta_const", []int64{0, 10, 20, 30, 40}, 64},
		{"delta_const_neg", []int64{100, 90, 80, 70, 60}, 64},
		{"gauge", []int64{100, 95, 105, 90, 110, 85, 115}, 64},
		{"counter", []int64{0, 10, 20, 30, 41, 50, 60}, 64},
		{"counter_simple", []int64{0, 10, 30, 60, 100, 150}, 64},
	}
	for _, tc := range testCases {
		b, mt, fv := MarshalValues(nil, tc.values, tc.precisionBits)
		decoded, err := UnmarshalValues(nil, b, mt, fv, len(tc.values))
		if err != nil {
			t.Fatalf("%s: UnmarshalValues error: %v", tc.name, err)
		}
		if !reflect.DeepEqual(decoded, tc.values) {
			t.Fatalf("%s: round-trip failed:\ngot  %v\nwant %v", tc.name, decoded, tc.values)
		}
	}
}

// --- Deduplication Tests ---

func floatsEqual(a, b []float64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if IsStaleNaN(a[i]) && IsStaleNaN(b[i]) {
			continue
		}
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestDeduplicateSamplesBasic(t *testing.T) {
	f := func(dedupIntervalMs int64, timestamps []int64, values []float64,
		wantTS []int64, wantVals []float64) {
		t.Helper()
		tsCopy := append([]int64{}, timestamps...)
		vCopy := append([]float64{}, values...)
		tsCopy, vCopy = DeduplicateSamples(tsCopy, vCopy, dedupIntervalMs)
		if !reflect.DeepEqual(tsCopy, wantTS) {
			t.Fatalf("timestamps:\ngot  %v\nwant %v\ninput: %v interval=%d",
				tsCopy, wantTS, timestamps, dedupIntervalMs)
		}
		if !floatsEqual(vCopy, wantVals) {
			t.Fatalf("values:\ngot  %v\nwant %v\ninput: %v interval=%d",
				vCopy, wantVals, timestamps, dedupIntervalMs)
		}
	}

	// No dedup needed
	f(1000, []int64{0, 2000}, []float64{1, 2},
		[]int64{0, 2000}, []float64{1, 2})

	// Single sample
	f(1000, []int64{500}, []float64{42},
		[]int64{500}, []float64{42})

	// Basic interval-based dedup (100ms interval)
	f(100,
		[]int64{0, 100, 100, 101, 150, 180, 205, 300, 1000},
		[]float64{0, 1, 2, 3, 4, 5, 6, 7, 8},
		[]int64{0, 100, 180, 300, 1000},
		[]float64{0, 2, 5, 7, 8})

	// 10-second interval
	f(10000,
		[]int64{10000, 13000, 21000, 22000, 30000, 33000, 39000, 45000},
		[]float64{0, 1, 2, 3, 4, 5, 6, 7},
		[]int64{10000, 13000, 30000, 39000, 45000},
		[]float64{0, 1, 4, 6, 7})

	// Disabled dedup (interval=0)
	f(0,
		[]int64{0, 0, 0, 1, 1},
		[]float64{0, 1, 2, 3, 4},
		[]int64{0, 0, 0, 1, 1},
		[]float64{0, 1, 2, 3, 4})
}

func TestDeduplicateIdenticalTimestamps(t *testing.T) {
	f := func(dedupIntervalMs int64, timestamps []int64, values []float64,
		wantTS []int64, wantVals []float64) {
		t.Helper()
		tsCopy := append([]int64{}, timestamps...)
		vCopy := append([]float64{}, values...)
		tsCopy, vCopy = DeduplicateSamples(tsCopy, vCopy, dedupIntervalMs)
		if !reflect.DeepEqual(tsCopy, wantTS) {
			t.Fatalf("timestamps:\ngot  %v\nwant %v", tsCopy, wantTS)
		}
		if !floatsEqual(vCopy, wantVals) {
			t.Fatalf("values:\ngot  %v\nwant %v", vCopy, wantVals)
		}
	}

	// Two identical timestamps: pick max value
	f(1000, []int64{1000, 1000}, []float64{2, 1},
		[]int64{1000}, []float64{2})

	// Three identical timestamps: pick max
	f(1000, []int64{1000, 1001, 1001, 1001, 2001},
		[]float64{1, 2, 5, 3, 0},
		[]int64{1000, 1001, 2001},
		[]float64{1, 5, 0})
}

func TestDeduplicateStaleNaN(t *testing.T) {
	f := func(dedupIntervalMs int64, timestamps []int64, values []float64,
		wantTS []int64, wantVals []float64) {
		t.Helper()
		tsCopy := append([]int64{}, timestamps...)
		vCopy := append([]float64{}, values...)
		tsCopy, vCopy = DeduplicateSamples(tsCopy, vCopy, dedupIntervalMs)
		if !reflect.DeepEqual(tsCopy, wantTS) {
			t.Fatalf("timestamps:\ngot  %v\nwant %v", tsCopy, wantTS)
		}
		if !floatsEqual(vCopy, wantVals) {
			t.Fatalf("values:\ngot  %v\nwant %v", vCopy, wantVals)
		}
	}

	// Prefer real value over StaleNaN
	f(1000, []int64{1000, 1000}, []float64{2, StaleNaN},
		[]int64{1000}, []float64{2})

	f(1000, []int64{1000, 1000}, []float64{StaleNaN, 2},
		[]int64{1000}, []float64{2})

	// Multiple samples: prefer non-StaleNaN, then max
	f(1000, []int64{1000, 1000, 1000}, []float64{1, StaleNaN, 2},
		[]int64{1000}, []float64{2})

	// All StaleNaN: keep StaleNaN
	f(1000, []int64{1000, 1000}, []float64{StaleNaN, StaleNaN},
		[]int64{1000}, []float64{StaleNaN})

	// StaleNaN with Inf
	f(1000, []int64{1000, 1000}, []float64{math.Inf(1), StaleNaN},
		[]int64{1000}, []float64{math.Inf(1)})

	// Mixed: real values and StaleNaN across intervals
	f(1000, []int64{1000, 1000, 2000, 2000},
		[]float64{1, StaleNaN, 2, 3},
		[]int64{1000, 2000}, []float64{1, 3})
}

// --- Block Header Tests ---

func TestBlockHeaderRoundTrip(t *testing.T) {
	headers := []BlockHeader{
		{
			MinTimestamp:          1000,
			MaxTimestamp:          2000,
			FirstValue:           42,
			RowsCount:            100,
			Scale:                -2,
			TimestampsMarshalType: MarshalTypeNearestDelta2,
			ValuesMarshalType:    MarshalTypeNearestDelta,
			PrecisionBits:        4,
		},
		{
			MinTimestamp:          0,
			MaxTimestamp:          0,
			FirstValue:           0,
			RowsCount:            1,
			Scale:                0,
			TimestampsMarshalType: MarshalTypeConst,
			ValuesMarshalType:    MarshalTypeConst,
			PrecisionBits:        64,
		},
		{
			MinTimestamp:          -1000,
			MaxTimestamp:          5000,
			FirstValue:           -999,
			RowsCount:            50000,
			Scale:                3,
			TimestampsMarshalType: MarshalTypeDeltaConst,
			ValuesMarshalType:    MarshalTypeNearestDelta2,
			PrecisionBits:        16,
		},
		{
			MinTimestamp:          math.MaxInt64 / 4,
			MaxTimestamp:          math.MaxInt64 / 2,
			FirstValue:           math.MinInt64 / 4,
			RowsCount:            math.MaxUint32,
			Scale:                -32000,
			TimestampsMarshalType: MarshalTypeNearestDelta,
			ValuesMarshalType:    MarshalTypeNearestDelta2,
			PrecisionBits:        1,
		},
	}

	for i, bh := range headers {
		data := bh.Marshal(nil)
		var bh2 BlockHeader
		tail, err := bh2.Unmarshal(data)
		if err != nil {
			t.Fatalf("header %d: Unmarshal error: %v", i, err)
		}
		if len(tail) != 0 {
			t.Fatalf("header %d: unexpected %d trailing bytes", i, len(tail))
		}
		if bh2 != bh {
			t.Fatalf("header %d round-trip failed:\ngot  %+v\nwant %+v", i, bh2, bh)
		}
	}
}

func TestBlockHeaderMultiple(t *testing.T) {
	// Marshal two headers consecutively, unmarshal both
	bh1 := BlockHeader{MinTimestamp: 100, MaxTimestamp: 200, FirstValue: 10,
		RowsCount: 5, Scale: -1, TimestampsMarshalType: 5, ValuesMarshalType: 6, PrecisionBits: 8}
	bh2 := BlockHeader{MinTimestamp: 300, MaxTimestamp: 400, FirstValue: 20,
		RowsCount: 10, Scale: 2, TimestampsMarshalType: 3, ValuesMarshalType: 2, PrecisionBits: 16}

	data := bh1.Marshal(nil)
	data = bh2.Marshal(data)

	var got1, got2 BlockHeader
	rest, err := got1.Unmarshal(data)
	if err != nil {
		t.Fatal(err)
	}
	rest, err = got2.Unmarshal(rest)
	if err != nil {
		t.Fatal(err)
	}
	if len(rest) != 0 {
		t.Fatalf("unexpected trailing bytes: %d", len(rest))
	}
	if got1 != bh1 {
		t.Fatalf("header 1 mismatch:\ngot  %+v\nwant %+v", got1, bh1)
	}
	if got2 != bh2 {
		t.Fatalf("header 2 mismatch:\ngot  %+v\nwant %+v", got2, bh2)
	}
}

// --- Full Pipeline Test ---

func TestFullPipeline(t *testing.T) {
	// Simulate a full encode/decode cycle for a block of time-series data
	timestamps := []int64{1000, 1010, 1020, 1030, 1040, 1050}
	values := []int64{100, 200, 300, 400, 500, 600}

	// Encode timestamps
	tsBytes, tsMT, tsFV := MarshalTimestamps(nil, timestamps, 64)
	// Encode values
	vBytes, vMT, vFV := MarshalValues(nil, values, 64)

	// Create block header
	bh := BlockHeader{
		MinTimestamp:          timestamps[0],
		MaxTimestamp:          timestamps[len(timestamps)-1],
		FirstValue:           vFV,
		RowsCount:            uint32(len(timestamps)),
		Scale:                0,
		TimestampsMarshalType: tsMT,
		ValuesMarshalType:    vMT,
		PrecisionBits:        64,
	}

	// Marshal block header
	headerBytes := bh.Marshal(nil)

	// Unmarshal block header
	var bh2 BlockHeader
	tail, err := bh2.Unmarshal(headerBytes)
	if err != nil {
		t.Fatal(err)
	}
	if len(tail) != 0 {
		t.Fatalf("unexpected trailing bytes after header: %d", len(tail))
	}

	// Decode timestamps
	decodedTS, err := UnmarshalTimestamps(nil, tsBytes, bh2.TimestampsMarshalType, tsFV, int(bh2.RowsCount))
	if err != nil {
		t.Fatalf("UnmarshalTimestamps error: %v", err)
	}
	if !reflect.DeepEqual(decodedTS, timestamps) {
		t.Fatalf("timestamps mismatch:\ngot  %v\nwant %v", decodedTS, timestamps)
	}

	// Decode values
	decodedVals, err := UnmarshalValues(nil, vBytes, bh2.ValuesMarshalType, bh2.FirstValue, int(bh2.RowsCount))
	if err != nil {
		t.Fatalf("UnmarshalValues error: %v", err)
	}
	if !reflect.DeepEqual(decodedVals, values) {
		t.Fatalf("values mismatch:\ngot  %v\nwant %v", decodedVals, values)
	}
}

func TestFullPipelineWithDedup(t *testing.T) {
	// Raw ingested samples with duplicates
	rawTS := []int64{1000, 1000, 1500, 2000, 2100, 2100, 3000}
	rawVals := []float64{10, 20, 30, 40, 50, 60, 70}

	// Deduplicate
	dedupTS, dedupVals := DeduplicateSamples(
		append([]int64{}, rawTS...),
		append([]float64{}, rawVals...),
		1000)

	// Convert float values to int64 for encoding
	intVals := make([]int64, len(dedupVals))
	for i, v := range dedupVals {
		intVals[i] = int64(v)
	}

	// Encode
	tsBytes, tsMT, tsFV := MarshalTimestamps(nil, dedupTS, 64)
	vBytes, vMT, vFV := MarshalValues(nil, intVals, 64)

	// Create and marshal header
	bh := BlockHeader{
		MinTimestamp:          dedupTS[0],
		MaxTimestamp:          dedupTS[len(dedupTS)-1],
		FirstValue:           vFV,
		RowsCount:            uint32(len(dedupTS)),
		Scale:                0,
		TimestampsMarshalType: tsMT,
		ValuesMarshalType:    vMT,
		PrecisionBits:        64,
	}
	headerBytes := bh.Marshal(nil)

	// Unmarshal header
	var bh2 BlockHeader
	_, err := bh2.Unmarshal(headerBytes)
	if err != nil {
		t.Fatal(err)
	}

	// Decode
	gotTS, err := UnmarshalTimestamps(nil, tsBytes, bh2.TimestampsMarshalType, tsFV, int(bh2.RowsCount))
	if err != nil {
		t.Fatal(err)
	}
	gotVals, err := UnmarshalValues(nil, vBytes, bh2.ValuesMarshalType, bh2.FirstValue, int(bh2.RowsCount))
	if err != nil {
		t.Fatal(err)
	}

	if !reflect.DeepEqual(gotTS, dedupTS) {
		t.Fatalf("decoded timestamps mismatch:\ngot  %v\nwant %v", gotTS, dedupTS)
	}

	// Compare decoded int64 values to expected
	for i := range gotVals {
		if gotVals[i] != intVals[i] {
			t.Fatalf("decoded value[%d] mismatch: got %d, want %d", i, gotVals[i], intVals[i])
		}
	}
}
