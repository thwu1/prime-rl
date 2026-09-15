package gorillachunk

// ValueType defines the type of a value an Iterator points to.
type ValueType uint8

// Possible values for ValueType.
const (
	ValNone  ValueType = iota // No value at the current position.
	ValFloat                  // A float value, retrieved with At.
)

// Iterator reads samples from a chunk in timestamp-increasing order.
type Iterator interface {
	// Next advances the iterator by one and returns the type of the value
	// at the new position (or ValNone if the iterator is exhausted).
	Next() ValueType

	// Seek advances the iterator forward to the first sample with a
	// timestamp equal or greater than t. If the current sample already
	// satisfies this property, Seek has no effect.
	Seek(t int64) ValueType

	// At returns the current timestamp/value pair.
	At() (int64, float64)

	// Err returns the current error (should be checked after exhaustion).
	Err() error
}

// Appender adds samples to a chunk.
type Appender interface {
	Append(t int64, v float64)
}
