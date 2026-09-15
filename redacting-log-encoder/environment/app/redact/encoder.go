package redact

import (
	"strings"
	"time"

	"go.uber.org/zap/buffer"
	"go.uber.org/zap/zapcore"
)


// Encoder wraps a zapcore.Encoder and redacts fields matching configured rules.
// Masking replaces a field's value with "[REDACTED]" (via AddString on the inner
// encoder regardless of the original type). Dropping omits the field entirely.
type Encoder struct {
	zapcore.Encoder
	cfg    *Config
	nsPath []string
}

// New creates a redacting encoder wrapping inner with the given config.
func New(inner zapcore.Encoder, cfg *Config) *Encoder {
	return &Encoder{
		Encoder: inner,
		cfg:     cfg,
	}
}

func (e *Encoder) currentPath(key string) string {
	if len(e.nsPath) == 0 {
		return key
	}
	return strings.Join(e.nsPath, ".") + "." + key
}

func (e *Encoder) matchRule(key string) *Rule {
	path := e.currentPath(key)
	for i := range e.cfg.Rules {
		if e.cfg.Rules[i].Match(path) {
			return &e.cfg.Rules[i]
		}
	}
	return nil
}

func (e *Encoder) checkRule(key string) (Action, bool) {
	r := e.matchRule(key)
	if r == nil {
		return 0, false
	}
	return r.Action, true
}

// --- Primitive field methods ---
// These correctly handle top-level redaction.

func (e *Encoder) AddString(key, val string) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddString(key, val)
}

func (e *Encoder) AddBool(key string, val bool) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddBool(key, val)
}

func (e *Encoder) AddInt(key string, val int) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddInt(key, val)
}

func (e *Encoder) AddInt64(key string, val int64) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddInt64(key, val)
}

func (e *Encoder) AddInt32(key string, val int32) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddInt32(key, val)
}

func (e *Encoder) AddInt16(key string, val int16) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddInt16(key, val)
}

func (e *Encoder) AddInt8(key string, val int8) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddInt8(key, val)
}

func (e *Encoder) AddUint64(key string, val uint64) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUint64(key, val)
}

func (e *Encoder) AddUint(key string, val uint) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUint(key, val)
}

func (e *Encoder) AddUint32(key string, val uint32) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUint32(key, val)
}

func (e *Encoder) AddUint16(key string, val uint16) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUint16(key, val)
}

func (e *Encoder) AddUint8(key string, val uint8) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUint8(key, val)
}

func (e *Encoder) AddUintptr(key string, val uintptr) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddUintptr(key, val)
}

func (e *Encoder) AddFloat64(key string, val float64) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddFloat64(key, val)
}

func (e *Encoder) AddFloat32(key string, val float32) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddFloat32(key, val)
}

func (e *Encoder) AddComplex128(key string, val complex128) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddComplex128(key, val)
}

func (e *Encoder) AddComplex64(key string, val complex64) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddComplex64(key, val)
}

func (e *Encoder) AddDuration(key string, val time.Duration) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddDuration(key, val)
}

func (e *Encoder) AddTime(key string, val time.Time) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddTime(key, val)
}

func (e *Encoder) AddBinary(key string, val []byte) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddBinary(key, val)
}

func (e *Encoder) AddByteString(key string, val []byte) {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return
	}
	e.Encoder.AddByteString(key, val)
}

func (e *Encoder) AddReflected(key string, val interface{}) error {
	if a, ok := e.checkRule(key); ok {
		if a == Mask {
			e.Encoder.AddString(key, "[REDACTED]")
		}
		return nil
	}
	return e.Encoder.AddReflected(key, val)
}

// --- Structured type methods ---

// AddObject delegates the object encoding to the inner encoder without
// intercepting the ObjectMarshaler's field calls, so nested fields are
// never checked against redaction rules.
func (e *Encoder) AddObject(key string, obj zapcore.ObjectMarshaler) error {
	if a, ok := e.checkRule(key); ok {
		switch a {
		case Drop:
			return nil
		case Mask:
			e.Encoder.AddString(key, "[REDACTED]")
			return nil
		}
	}
	return e.Encoder.AddObject(key, obj)
}

// AddArray delegates the array encoding to the inner encoder without
// intercepting objects within the array.
func (e *Encoder) AddArray(key string, arr zapcore.ArrayMarshaler) error {
	if a, ok := e.checkRule(key); ok {
		switch a {
		case Drop:
			return nil
		case Mask:
			e.Encoder.AddString(key, "[REDACTED]")
			return nil
		}
	}
	return e.Encoder.AddArray(key, arr)
}

// OpenNamespace tracks the namespace path for rule matching.
func (e *Encoder) OpenNamespace(key string) {
	e.nsPath = append(e.nsPath, key)
	e.Encoder.OpenNamespace(key)
}

// Clone returns a copy of the inner encoder but does not wrap it
// in a RedactingEncoder, so the cloned encoder has no redaction.
func (e *Encoder) Clone() zapcore.Encoder {
	return e.Encoder.Clone()
}

// EncodeEntry forwards fields directly to the inner encoder without
// applying any redaction rules.
func (e *Encoder) EncodeEntry(entry zapcore.Entry, fields []zapcore.Field) (*buffer.Buffer, error) {
	return e.Encoder.EncodeEntry(entry, fields)
}
