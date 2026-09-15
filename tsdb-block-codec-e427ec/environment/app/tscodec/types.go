package tscodec

import (
	"fmt"
	"math"
)

// MarshalType defines how values are encoded in a block.
type MarshalType byte

const (
	// MarshalTypeZSTDNearestDelta2 is used for counter timeseries (delta-of-delta + zstd).
	MarshalTypeZSTDNearestDelta2 MarshalType = 1

	// MarshalTypeDeltaConst is used for constantly changing timeseries with constant delta.
	MarshalTypeDeltaConst MarshalType = 2

	// MarshalTypeConst is used for timeseries containing only a single constant.
	MarshalTypeConst MarshalType = 3

	// MarshalTypeZSTDNearestDelta is used for gauge timeseries (delta + zstd).
	MarshalTypeZSTDNearestDelta MarshalType = 4

	// MarshalTypeNearestDelta2 is used instead of MarshalTypeZSTDNearestDelta2
	// when compression doesn't help.
	MarshalTypeNearestDelta2 MarshalType = 5

	// MarshalTypeNearestDelta is used instead of MarshalTypeZSTDNearestDelta
	// when compression doesn't help.
	MarshalTypeNearestDelta MarshalType = 6
)

// CheckMarshalType verifies whether the mt is valid.
func CheckMarshalType(mt MarshalType) error {
	if mt < 1 || mt > 6 {
		return fmt.Errorf("invalid MarshalType: %d; must be in range [1..6]", mt)
	}
	return nil
}

// CheckPrecisionBits validates precisionBits range.
func CheckPrecisionBits(precisionBits uint8) error {
	if precisionBits < 1 || precisionBits > 64 {
		return fmt.Errorf("precisionBits must be in range [1..64]; got %d", precisionBits)
	}
	return nil
}

// StaleNaN is a special float64 value used as a staleness marker.
var StaleNaN = math.Float64frombits(0x7ff0000000000002)

// IsStaleNaN returns true if v is a staleness NaN marker.
func IsStaleNaN(v float64) bool {
	return math.Float64bits(v) == 0x7ff0000000000002
}

// BlockHeader contains metadata for a time-series data block.
type BlockHeader struct {
	MinTimestamp           int64
	MaxTimestamp           int64
	FirstValue             int64
	RowsCount              uint32
	Scale                  int16
	TimestampsMarshalType  MarshalType
	ValuesMarshalType      MarshalType
	PrecisionBits          uint8
}
