package gorillachunk

import (
	"math"
	"testing"
)


func catchPanic(t *testing.T) {
	t.Helper()
	if r := recover(); r != nil {
		t.Fatalf("panic: %v", r)
	}
}

func requireNoError(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// ---------- XOR round-trip tests ----------

func TestXORBasicRoundTrip(t *testing.T) {
	defer catchPanic(t)
	c := NewXORChunk()
	app, err := c.Appender()
	requireNoError(t, err)

	timestamps := []int64{1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000}
	values := []float64{100.5, 200.3, 150.7, 300.1, 250.9, 50.2, 175.8, 420.6, 310.4, 89.1}

	for i := range timestamps {
		app.Append(timestamps[i], values[i])
	}

	if c.NumSamples() != len(timestamps) {
		t.Fatalf("expected %d samples, got %d", len(timestamps), c.NumSamples())
	}

	it := c.Iterator(nil)
	for i := range timestamps {
		vt := it.Next()
		if vt != ValFloat {
			t.Fatalf("sample %d: expected ValFloat, got %v", i, vt)
		}
		ts, v := it.At()
		if ts != timestamps[i] {
			t.Fatalf("sample %d: expected t=%d, got t=%d", i, timestamps[i], ts)
		}
		if math.Float64bits(v) != math.Float64bits(values[i]) {
			t.Fatalf("sample %d: expected v=%v (bits:%016x), got v=%v (bits:%016x)",
				i, values[i], math.Float64bits(values[i]), v, math.Float64bits(v))
		}
	}
	if it.Next() != ValNone {
		t.Fatal("expected end of iteration")
	}
	requireNoError(t, it.Err())

	// Test iterator reuse.
	it2 := c.Iterator(it)
	for i := range timestamps {
		if it2.Next() != ValFloat {
			t.Fatalf("reuse: sample %d: expected ValFloat", i)
		}
		ts, v := it2.At()
		if ts != timestamps[i] || math.Float64bits(v) != math.Float64bits(values[i]) {
			t.Fatalf("reuse: sample %d mismatch", i)
		}
	}
	requireNoError(t, it2.Err())
}

// TestXORLeadingZeroClamp tests round-trip for values whose XOR delta
// has 32 or more leading zeros.
func TestXORLeadingZeroClamp(t *testing.T) {
	defer catchPanic(t)

	xorDeltas := []uint64{
		0x0000000080000000, // 32 leading zeros
		0x0000000000800000, // 40 leading zeros
		0x0000000000008000, // 48 leading zeros
		0x0000000000000080, // 56 leading zeros
		0x0000000000000002, // 62 leading zeros
		0x0000000000000001, // 63 leading zeros
	}

	for _, xorDelta := range xorDeltas {
		c := NewXORChunk()
		app, err := c.Appender()
		requireNoError(t, err)

		v1 := 2.0
		v2 := math.Float64frombits(math.Float64bits(v1) ^ xorDelta)

		app.Append(1000, v1)
		app.Append(2000, v2)

		it := c.Iterator(nil)
		if it.Next() != ValFloat {
			t.Fatalf("xorDelta=%016x: expected first sample", xorDelta)
		}
		ts, v := it.At()
		if ts != 1000 || math.Float64bits(v) != math.Float64bits(v1) {
			t.Fatalf("xorDelta=%016x: first sample wrong", xorDelta)
		}

		if it.Next() != ValFloat {
			t.Fatalf("xorDelta=%016x: expected second sample", xorDelta)
		}
		ts, v = it.At()
		if ts != 2000 {
			t.Fatalf("xorDelta=%016x: expected t=2000, got t=%d", xorDelta, ts)
		}
		if math.Float64bits(v) != math.Float64bits(v2) {
			t.Fatalf("xorDelta=%016x: expected v=%v (bits:%016x), got v=%v (bits:%016x)",
				xorDelta, v2, math.Float64bits(v2), v, math.Float64bits(v))
		}
		requireNoError(t, it.Err())
	}
}

// TestXORSignificantBitsOverflow tests round-trip for values whose XOR delta
// has 0 leading zeros and 0 trailing zeros (64 significant bits).
func TestXORSignificantBitsOverflow(t *testing.T) {
	defer catchPanic(t)

	// XOR deltas with bit 63 AND bit 0 both set → leading=0, trailing=0, sigbits=64.
	xorDeltas := []uint64{
		0x8000000000000001,
		0x8000000000000003,
		0xFFFFFFFFFFFFFFFF,
		0x8100000000000001,
	}

	for _, xorDelta := range xorDeltas {
		c := NewXORChunk()
		app, err := c.Appender()
		requireNoError(t, err)

		v1 := 1.0
		v2 := math.Float64frombits(math.Float64bits(v1) ^ xorDelta)

		app.Append(1000, v1)
		app.Append(2000, v2)

		it := c.Iterator(nil)
		it.Next()
		if it.Next() != ValFloat {
			t.Fatalf("xorDelta=%016x: expected second sample", xorDelta)
		}
		ts, v := it.At()
		if ts != 2000 {
			t.Fatalf("xorDelta=%016x: expected t=2000, got t=%d", xorDelta, ts)
		}
		if math.Float64bits(v) != math.Float64bits(v2) {
			t.Fatalf("xorDelta=%016x: expected v bits %016x, got %016x",
				xorDelta, math.Float64bits(v2), math.Float64bits(v))
		}
		requireNoError(t, it.Err())
	}
}

// TestXORDodBoundaryValue tests timestamp delta-of-delta at the exact
// maximum positive boundary of each size bucket.
func TestXORDodBoundaryValue(t *testing.T) {
	defer catchPanic(t)

	// Max positive dod values for each bucket.
	dodValues := []int64{
		1 << 13, // 8192: max positive for 14-bit bucket
		1 << 16, // 65536: max positive for 17-bit bucket
		1 << 19, // 524288: max positive for 20-bit bucket
	}

	for _, dod := range dodValues {
		c := NewXORChunk()
		app, err := c.Appender()
		requireNoError(t, err)

		t0 := int64(0)
		t1 := int64(10000)
		tDelta := t1 - t0
		t2 := t1 + tDelta + dod // produces the target dod

		app.Append(t0, 1.0)
		app.Append(t1, 1.0)
		app.Append(t2, 1.0)

		it := c.Iterator(nil)
		it.Next() // t0
		it.Next() // t1

		if it.Next() != ValFloat {
			t.Fatalf("dod=%d: expected third sample", dod)
		}
		ts, _ := it.At()
		if ts != t2 {
			t.Fatalf("dod=%d: expected t=%d, got t=%d (diff=%d)", dod, t2, ts, ts-t2)
		}
		requireNoError(t, it.Err())
	}

	// Also test negative boundary values.
	negDodValues := []int64{
		-((1 << 13) - 1), // -8191: min negative for 14-bit bucket
		-((1 << 16) - 1), // -65535: min negative for 17-bit bucket
		-((1 << 19) - 1), // -524287: min negative for 20-bit bucket
	}

	for _, dod := range negDodValues {
		c := NewXORChunk()
		app, err := c.Appender()
		requireNoError(t, err)

		t0 := int64(0)
		t1 := int64(1000000) // large enough that t2 stays positive
		tDelta := t1 - t0
		t2 := t1 + tDelta + dod

		app.Append(t0, 1.0)
		app.Append(t1, 1.0)
		app.Append(t2, 1.0)

		it := c.Iterator(nil)
		it.Next()
		it.Next()

		if it.Next() != ValFloat {
			t.Fatalf("dod=%d: expected third sample", dod)
		}
		ts, _ := it.At()
		if ts != t2 {
			t.Fatalf("dod=%d: expected t=%d, got t=%d", dod, t2, ts)
		}
		requireNoError(t, it.Err())
	}
}

func TestXORSeeking(t *testing.T) {
	defer catchPanic(t)
	c := NewXORChunk()
	app, err := c.Appender()
	requireNoError(t, err)

	for i := int64(0); i < 20; i++ {
		app.Append(i*1000, float64(i)*10.0)
	}

	// Seek to middle.
	it := c.Iterator(nil)
	if it.Seek(10000) != ValFloat {
		t.Fatal("seek to 10000 failed")
	}
	ts, v := it.At()
	if ts != 10000 || v != 100.0 {
		t.Fatalf("seek: expected (10000, 100.0), got (%d, %v)", ts, v)
	}

	// Continue iteration after seek.
	if it.Next() != ValFloat {
		t.Fatal("expected sample after seek")
	}
	ts, v = it.At()
	if ts != 11000 || v != 110.0 {
		t.Fatalf("after seek: expected (11000, 110.0), got (%d, %v)", ts, v)
	}

	// Seek past end.
	if it.Seek(999999) != ValNone {
		t.Fatal("seek past end should return ValNone")
	}

	// Seek to exact first sample.
	it2 := c.Iterator(nil)
	if it2.Seek(0) != ValFloat {
		t.Fatal("seek to 0 failed")
	}
	ts, v = it2.At()
	if ts != 0 || v != 0.0 {
		t.Fatalf("seek to 0: expected (0, 0.0), got (%d, %v)", ts, v)
	}

	// Seek to between-samples timestamp.
	it3 := c.Iterator(nil)
	if it3.Seek(5500) != ValFloat {
		t.Fatal("seek to 5500 failed")
	}
	ts, _ = it3.At()
	if ts != 6000 {
		t.Fatalf("seek to 5500: expected t=6000, got t=%d", ts)
	}
}

func TestXORSpecialValues(t *testing.T) {
	defer catchPanic(t)
	c := NewXORChunk()
	app, err := c.Appender()
	requireNoError(t, err)

	specialValues := []float64{
		0.0,
		math.Copysign(0, -1), // -0.0
		math.Inf(1),
		math.Inf(-1),
		math.NaN(),
		1e308,
		-1e308,
		5e-324,  // smallest positive subnormal
		-5e-324, // smallest negative subnormal
	}

	for i, v := range specialValues {
		app.Append(int64(i*1000), v)
	}

	it := c.Iterator(nil)
	for i, expected := range specialValues {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != int64(i*1000) {
			t.Fatalf("sample %d: expected t=%d, got t=%d", i, int64(i*1000), ts)
		}
		if math.Float64bits(v) != math.Float64bits(expected) {
			t.Fatalf("sample %d: expected bits %016x, got bits %016x",
				i, math.Float64bits(expected), math.Float64bits(v))
		}
	}
	requireNoError(t, it.Err())
}

func TestXORAppenderResume(t *testing.T) {
	defer catchPanic(t)
	c := NewXORChunk()

	// First batch.
	app1, err := c.Appender()
	requireNoError(t, err)
	app1.Append(1000, 1.0)
	app1.Append(2000, 2.0)
	app1.Append(3000, 3.0)

	// Resume with new appender.
	app2, err := c.Appender()
	requireNoError(t, err)
	app2.Append(4000, 4.0)
	app2.Append(5000, 5.0)

	if c.NumSamples() != 5 {
		t.Fatalf("expected 5 samples, got %d", c.NumSamples())
	}

	expected := []struct {
		t int64
		v float64
	}{
		{1000, 1.0}, {2000, 2.0}, {3000, 3.0}, {4000, 4.0}, {5000, 5.0},
	}

	it := c.Iterator(nil)
	for i, e := range expected {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != e.t || math.Float64bits(v) != math.Float64bits(e.v) {
			t.Fatalf("sample %d: expected (%d, %v), got (%d, %v)", i, e.t, e.v, ts, v)
		}
	}
	if it.Next() != ValNone {
		t.Fatal("expected end")
	}
	requireNoError(t, it.Err())
}

func TestXORNegativeTimestamps(t *testing.T) {
	defer catchPanic(t)
	c := NewXORChunk()
	app, err := c.Appender()
	requireNoError(t, err)

	timestamps := []int64{-5000, -4000, -3000, -1000, 0, 1000}
	values := []float64{10.0, 20.0, 30.0, 40.0, 50.0, 60.0}

	for i := range timestamps {
		app.Append(timestamps[i], values[i])
	}

	it := c.Iterator(nil)
	for i := range timestamps {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != timestamps[i] || v != values[i] {
			t.Fatalf("sample %d: expected (%d, %v), got (%d, %v)",
				i, timestamps[i], values[i], ts, v)
		}
	}
	requireNoError(t, it.Err())
}

// ---------- Varbit tests ----------

func TestVarbitIntRoundTrip(t *testing.T) {
	defer catchPanic(t)

	testValues := []int64{
		0, 1, -1, 2, -2, 3, -3, 4,
		10, -10, 31, -31, 32,
		100, -100, 255, -255, 256,
		1000, -1000, 2047, -2047, 2048,
		100000, -100000, 131072, -131071,
		1000000, -1000000, 16777216, -16777215,
		1<<40, -(1 << 40),
		1<<55, -(1 << 55),
		math.MaxInt64, math.MinInt64, math.MinInt64 + 1,
	}

	for _, val := range testValues {
		bs := &bstream{}
		putVarbitInt(bs, val)

		br := newBReader(bs.bytes())
		decoded, err := readVarbitInt(&br)
		requireNoError(t, err)
		if decoded != val {
			t.Fatalf("varbitInt(%d): decoded %d", val, decoded)
		}
	}
}

func TestVarbitUintRoundTrip(t *testing.T) {
	defer catchPanic(t)

	testValues := []uint64{
		0, 1, 2, 3, 5, 7,
		8, 10, 32, 63,
		64, 100, 255, 511,
		512, 1000, 4095,
		4096, 100000, 262143,
		262144, 1000000, 33554431,
		33554432, 1 << 40, 72057594037927935,
		72057594037927936, 1 << 60, math.MaxUint64,
	}

	for _, val := range testValues {
		bs := &bstream{}
		putVarbitUint(bs, val)

		br := newBReader(bs.bytes())
		decoded, err := readVarbitUint(&br)
		requireNoError(t, err)
		if decoded != val {
			t.Fatalf("varbitUint(%d): decoded %d", val, decoded)
		}
	}
}

func TestVarbitBoundaryValues(t *testing.T) {
	defer catchPanic(t)

	// Test exact boundary values for each bucket.
	intBoundaries := []int64{
		// 3-bit bucket boundaries: -3 to 4
		-3, 4,
		// 6-bit: -31 to 32
		-31, 32,
		// 9-bit: -255 to 256
		-255, 256,
		// 12-bit: -2047 to 2048
		-2047, 2048,
		// 18-bit
		-((1 << 17) - 1), 1 << 17,
		// 25-bit
		-((1 << 24) - 1), 1 << 24,
		// 56-bit
		-((1 << 55) - 1), 1 << 55,
	}

	for _, val := range intBoundaries {
		bs := &bstream{}
		putVarbitInt(bs, val)

		br := newBReader(bs.bytes())
		decoded, err := readVarbitInt(&br)
		requireNoError(t, err)
		if decoded != val {
			t.Fatalf("varbitInt boundary(%d): decoded %d", val, decoded)
		}
	}

	// Values just outside each bucket (should go to next bucket).
	outsideBucket := []int64{
		5, -4,   // outside 3-bit
		33, -32, // outside 6-bit
		257, -256,
		2049, -2048,
	}

	for _, val := range outsideBucket {
		bs := &bstream{}
		putVarbitInt(bs, val)

		br := newBReader(bs.bytes())
		decoded, err := readVarbitInt(&br)
		requireNoError(t, err)
		if decoded != val {
			t.Fatalf("varbitInt outside(%d): decoded %d", val, decoded)
		}
	}

	// Test multiple varbit values written sequentially.
	bs := &bstream{}
	sequence := []int64{0, 5, -100, 2048, -131071, 16777216, 0, -1}
	for _, val := range sequence {
		putVarbitInt(bs, val)
	}

	br := newBReader(bs.bytes())
	for _, expected := range sequence {
		decoded, err := readVarbitInt(&br)
		requireNoError(t, err)
		if decoded != expected {
			t.Fatalf("varbitInt sequence: expected %d, decoded %d", expected, decoded)
		}
	}
}

// ---------- Merge tests ----------

func TestMergeBasic(t *testing.T) {
	defer catchPanic(t)

	a := NewXORChunk()
	aApp, err := a.Appender()
	requireNoError(t, err)
	aApp.Append(1000, 1.0)
	aApp.Append(3000, 3.0)
	aApp.Append(5000, 5.0)

	b := NewXORChunk()
	bApp, err := b.Appender()
	requireNoError(t, err)
	bApp.Append(2000, 2.0)
	bApp.Append(4000, 4.0)
	bApp.Append(6000, 6.0)

	merged, err := MergeChunks(a, b)
	requireNoError(t, err)

	expectedTs := []int64{1000, 2000, 3000, 4000, 5000, 6000}
	expectedVs := []float64{1.0, 2.0, 3.0, 4.0, 5.0, 6.0}

	if merged.NumSamples() != len(expectedTs) {
		t.Fatalf("expected %d samples, got %d", len(expectedTs), merged.NumSamples())
	}

	it := merged.Iterator(nil)
	for i := range expectedTs {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != expectedTs[i] || math.Float64bits(v) != math.Float64bits(expectedVs[i]) {
			t.Fatalf("sample %d: expected (%d, %v), got (%d, %v)",
				i, expectedTs[i], expectedVs[i], ts, v)
		}
	}
	if it.Next() != ValNone {
		t.Fatal("expected end")
	}
	requireNoError(t, it.Err())
}

func TestMergeOverlapping(t *testing.T) {
	defer catchPanic(t)

	a := NewXORChunk()
	aApp, err := a.Appender()
	requireNoError(t, err)
	aApp.Append(1000, 10.0)
	aApp.Append(2000, 20.0)
	aApp.Append(3000, 30.0)
	aApp.Append(4000, 40.0)
	aApp.Append(5000, 50.0)

	b := NewXORChunk()
	bApp, err := b.Appender()
	requireNoError(t, err)
	bApp.Append(3500, 35.0)
	bApp.Append(6000, 60.0)
	bApp.Append(7000, 70.0)

	merged, err := MergeChunks(a, b)
	requireNoError(t, err)

	expectedTs := []int64{1000, 2000, 3000, 3500, 4000, 5000, 6000, 7000}
	expectedVs := []float64{10.0, 20.0, 30.0, 35.0, 40.0, 50.0, 60.0, 70.0}

	if merged.NumSamples() != len(expectedTs) {
		t.Fatalf("expected %d samples, got %d", len(expectedTs), merged.NumSamples())
	}

	it := merged.Iterator(nil)
	for i := range expectedTs {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != expectedTs[i] || math.Float64bits(v) != math.Float64bits(expectedVs[i]) {
			t.Fatalf("sample %d: expected (%d, %v), got (%d, %v)",
				i, expectedTs[i], expectedVs[i], ts, v)
		}
	}
	requireNoError(t, it.Err())
}

func TestMergeEmpty(t *testing.T) {
	defer catchPanic(t)

	// Both empty.
	a := NewXORChunk()
	b := NewXORChunk()
	merged, err := MergeChunks(a, b)
	requireNoError(t, err)
	if merged.NumSamples() != 0 {
		t.Fatalf("both empty: expected 0 samples, got %d", merged.NumSamples())
	}

	// One empty.
	c := NewXORChunk()
	cApp, err := c.Appender()
	requireNoError(t, err)
	cApp.Append(1000, 1.0)
	cApp.Append(2000, 2.0)

	merged, err = MergeChunks(c, NewXORChunk())
	requireNoError(t, err)
	if merged.NumSamples() != 2 {
		t.Fatalf("one empty (b): expected 2 samples, got %d", merged.NumSamples())
	}

	merged, err = MergeChunks(NewXORChunk(), c)
	requireNoError(t, err)
	if merged.NumSamples() != 2 {
		t.Fatalf("one empty (a): expected 2 samples, got %d", merged.NumSamples())
	}

	// Verify content of non-empty merge.
	it := merged.Iterator(nil)
	it.Next()
	ts, v := it.At()
	if ts != 1000 || v != 1.0 {
		t.Fatalf("expected (1000, 1.0), got (%d, %v)", ts, v)
	}
	it.Next()
	ts, v = it.At()
	if ts != 2000 || v != 2.0 {
		t.Fatalf("expected (2000, 2.0), got (%d, %v)", ts, v)
	}
}

func TestMergeDedup(t *testing.T) {
	defer catchPanic(t)

	a := NewXORChunk()
	aApp, err := a.Appender()
	requireNoError(t, err)
	aApp.Append(1000, 100.0) // duplicate timestamp
	aApp.Append(2000, 200.0)
	aApp.Append(3000, 300.0) // duplicate timestamp

	b := NewXORChunk()
	bApp, err := b.Appender()
	requireNoError(t, err)
	bApp.Append(1000, 999.0) // should be discarded (a wins)
	bApp.Append(2500, 250.0)
	bApp.Append(3000, 888.0) // should be discarded (a wins)
	bApp.Append(4000, 400.0)

	merged, err := MergeChunks(a, b)
	requireNoError(t, err)

	expectedTs := []int64{1000, 2000, 2500, 3000, 4000}
	expectedVs := []float64{100.0, 200.0, 250.0, 300.0, 400.0}

	if merged.NumSamples() != len(expectedTs) {
		t.Fatalf("expected %d samples, got %d", len(expectedTs), merged.NumSamples())
	}

	it := merged.Iterator(nil)
	for i := range expectedTs {
		if it.Next() != ValFloat {
			t.Fatalf("sample %d: expected ValFloat", i)
		}
		ts, v := it.At()
		if ts != expectedTs[i] {
			t.Fatalf("sample %d: expected t=%d, got t=%d", i, expectedTs[i], ts)
		}
		if math.Float64bits(v) != math.Float64bits(expectedVs[i]) {
			t.Fatalf("sample %d: expected v=%v, got v=%v (a's value should win at duplicates)",
				i, expectedVs[i], v)
		}
	}
	requireNoError(t, it.Err())
}
