package redact

import (
	"strings"
	"time"

	"go.uber.org/zap/buffer"
	"go.uber.org/zap/zapcore"
)


// Encoder wraps a zapcore.Encoder and redacts fields matching configured rules.
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
	// Wrap the ObjectMarshaler so that its Add* calls are intercepted
	// by an objectRedactor at the correct namespace depth.
	nsPath := appendCopy(e.nsPath, key)
	wrapped := zapcore.ObjectMarshalerFunc(func(enc zapcore.ObjectEncoder) error {
		child := &objectRedactor{
			ObjectEncoder: enc,
			cfg:           e.cfg,
			nsPath:        nsPath,
		}
		return obj.MarshalLogObject(child)
	})
	return e.Encoder.AddObject(key, wrapped)
}

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
	nsPath := appendCopy(e.nsPath, key)
	wrapped := zapcore.ArrayMarshalerFunc(func(enc zapcore.ArrayEncoder) error {
		child := &arrayRedactor{
			ArrayEncoder: enc,
			cfg:          e.cfg,
			nsPath:       nsPath,
		}
		return arr.MarshalLogArray(child)
	})
	return e.Encoder.AddArray(key, wrapped)
}

func (e *Encoder) OpenNamespace(key string) {
	e.nsPath = append(e.nsPath, key)
	e.Encoder.OpenNamespace(key)
}

func (e *Encoder) Clone() zapcore.Encoder {
	return &Encoder{
		Encoder: e.Encoder.Clone(),
		cfg:     e.cfg,
		nsPath:  copySlice(e.nsPath),
	}
}

func (e *Encoder) EncodeEntry(entry zapcore.Entry, fields []zapcore.Field) (*buffer.Buffer, error) {
	if len(fields) == 0 {
		return e.Encoder.EncodeEntry(entry, nil)
	}
	// Clone the inner encoder so we can add redacted fields to its context
	// without modifying the original encoder's state.
	innerClone := e.Encoder.Clone()
	wrapper := &Encoder{
		Encoder: innerClone,
		cfg:     e.cfg,
		nsPath:  copySlice(e.nsPath),
	}
	for _, f := range fields {
		f.AddTo(wrapper)
	}
	return wrapper.Encoder.EncodeEntry(entry, nil)
}

// ============================================================
// objectRedactor wraps a zapcore.ObjectEncoder to apply redaction
// rules at the correct namespace depth inside nested objects.
// ============================================================

type objectRedactor struct {
	zapcore.ObjectEncoder
	cfg    *Config
	nsPath []string
}

func (o *objectRedactor) currentPath(key string) string {
	if len(o.nsPath) == 0 {
		return key
	}
	return strings.Join(o.nsPath, ".") + "." + key
}

func (o *objectRedactor) matchRule(key string) *Rule {
	path := o.currentPath(key)
	for i := range o.cfg.Rules {
		if o.cfg.Rules[i].Match(path) {
			return &o.cfg.Rules[i]
		}
	}
	return nil
}

func (o *objectRedactor) checkRule(key string) (Action, bool) {
	r := o.matchRule(key)
	if r == nil {
		return 0, false
	}
	return r.Action, true
}

func (o *objectRedactor) AddString(key, val string) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddString(key, val)
}

func (o *objectRedactor) AddBool(key string, val bool) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddBool(key, val)
}

func (o *objectRedactor) AddInt(key string, val int) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddInt(key, val)
}

func (o *objectRedactor) AddInt64(key string, val int64) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddInt64(key, val)
}

func (o *objectRedactor) AddInt32(key string, val int32) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddInt32(key, val)
}

func (o *objectRedactor) AddInt16(key string, val int16) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddInt16(key, val)
}

func (o *objectRedactor) AddInt8(key string, val int8) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddInt8(key, val)
}

func (o *objectRedactor) AddUint64(key string, val uint64) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUint64(key, val)
}

func (o *objectRedactor) AddUint(key string, val uint) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUint(key, val)
}

func (o *objectRedactor) AddUint32(key string, val uint32) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUint32(key, val)
}

func (o *objectRedactor) AddUint16(key string, val uint16) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUint16(key, val)
}

func (o *objectRedactor) AddUint8(key string, val uint8) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUint8(key, val)
}

func (o *objectRedactor) AddUintptr(key string, val uintptr) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddUintptr(key, val)
}

func (o *objectRedactor) AddFloat64(key string, val float64) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddFloat64(key, val)
}

func (o *objectRedactor) AddFloat32(key string, val float32) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddFloat32(key, val)
}

func (o *objectRedactor) AddComplex128(key string, val complex128) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddComplex128(key, val)
}

func (o *objectRedactor) AddComplex64(key string, val complex64) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddComplex64(key, val)
}

func (o *objectRedactor) AddDuration(key string, val time.Duration) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddDuration(key, val)
}

func (o *objectRedactor) AddTime(key string, val time.Time) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddTime(key, val)
}

func (o *objectRedactor) AddBinary(key string, val []byte) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddBinary(key, val)
}

func (o *objectRedactor) AddByteString(key string, val []byte) {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return
	}
	o.ObjectEncoder.AddByteString(key, val)
}

func (o *objectRedactor) AddReflected(key string, val interface{}) error {
	if a, ok := o.checkRule(key); ok {
		if a == Mask {
			o.ObjectEncoder.AddString(key, "[REDACTED]")
		}
		return nil
	}
	return o.ObjectEncoder.AddReflected(key, val)
}

func (o *objectRedactor) AddObject(key string, obj zapcore.ObjectMarshaler) error {
	if a, ok := o.checkRule(key); ok {
		switch a {
		case Drop:
			return nil
		case Mask:
			o.ObjectEncoder.AddString(key, "[REDACTED]")
			return nil
		}
	}
	nsPath := appendCopy(o.nsPath, key)
	wrapped := zapcore.ObjectMarshalerFunc(func(enc zapcore.ObjectEncoder) error {
		child := &objectRedactor{
			ObjectEncoder: enc,
			cfg:           o.cfg,
			nsPath:        nsPath,
		}
		return obj.MarshalLogObject(child)
	})
	return o.ObjectEncoder.AddObject(key, wrapped)
}

func (o *objectRedactor) AddArray(key string, arr zapcore.ArrayMarshaler) error {
	if a, ok := o.checkRule(key); ok {
		switch a {
		case Drop:
			return nil
		case Mask:
			o.ObjectEncoder.AddString(key, "[REDACTED]")
			return nil
		}
	}
	nsPath := appendCopy(o.nsPath, key)
	wrapped := zapcore.ArrayMarshalerFunc(func(enc zapcore.ArrayEncoder) error {
		child := &arrayRedactor{
			ArrayEncoder: enc,
			cfg:          o.cfg,
			nsPath:       nsPath,
		}
		return arr.MarshalLogArray(child)
	})
	return o.ObjectEncoder.AddArray(key, wrapped)
}

func (o *objectRedactor) OpenNamespace(key string) {
	o.nsPath = append(o.nsPath, key)
	o.ObjectEncoder.OpenNamespace(key)
}

// ============================================================
// arrayRedactor wraps a zapcore.ArrayEncoder to apply redaction
// to objects appended to arrays.
// ============================================================

type arrayRedactor struct {
	zapcore.ArrayEncoder
	cfg    *Config
	nsPath []string
}

func (a *arrayRedactor) AppendObject(obj zapcore.ObjectMarshaler) error {
	nsPath := copySlice(a.nsPath)
	wrapped := zapcore.ObjectMarshalerFunc(func(enc zapcore.ObjectEncoder) error {
		child := &objectRedactor{
			ObjectEncoder: enc,
			cfg:           a.cfg,
			nsPath:        nsPath,
		}
		return obj.MarshalLogObject(child)
	})
	return a.ArrayEncoder.AppendObject(wrapped)
}

func (a *arrayRedactor) AppendArray(arr zapcore.ArrayMarshaler) error {
	nsPath := copySlice(a.nsPath)
	wrapped := zapcore.ArrayMarshalerFunc(func(enc zapcore.ArrayEncoder) error {
		child := &arrayRedactor{
			ArrayEncoder: enc,
			cfg:          a.cfg,
			nsPath:       nsPath,
		}
		return arr.MarshalLogArray(child)
	})
	return a.ArrayEncoder.AppendArray(wrapped)
}

// --- helpers ---

func copySlice(s []string) []string {
	if s == nil {
		return nil
	}
	c := make([]string, len(s))
	copy(c, s)
	return c
}

func appendCopy(s []string, elem string) []string {
	c := make([]string, len(s)+1)
	copy(c, s)
	c[len(s)] = elem
	return c
}
