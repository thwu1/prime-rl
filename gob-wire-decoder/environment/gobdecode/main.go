// Package main implements a gob wire-format decoder that reads a binary
// gob stream from stdin and writes a JSON array to stdout.
// This implementation does NOT use encoding/gob.
//
package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
)

// Predefined type IDs from the gob wire format specification.
const (
	tidBool      = 1
	tidInt       = 2
	tidUint      = 3
	tidFloat     = 4
	tidBytes     = 5
	tidString    = 6
	tidComplex   = 7
	tidInterface = 8

	tidWireType   = 16
	tidArrayType  = 17
	tidCommonType = 18
	tidSliceType  = 19
	tidStructType = 20
	tidFieldType  = 21
	tidFieldSlice = 22
	tidMapType    = 23

	firstUserID = 65
)

// Type descriptor kinds.
const (
	kindStruct = iota
	kindArray
	kindSlice
	kindMap
)

type fieldDef struct {
	Name   string
	TypeID int
}

type typeDef struct {
	Name   string
	ID     int
	Kind   int
	Fields []fieldDef // struct fields
	Elem   int        // element type for array/slice/map
	Key    int        // key type for map
	Len    int        // fixed length for array
}

type decoder struct {
	data  []byte
	pos   int
	types map[int]*typeDef
}

func newDecoder(data []byte) *decoder {
	return &decoder{data: data, pos: 0, types: make(map[int]*typeDef)}
}

func (d *decoder) remaining() int { return len(d.data) - d.pos }

func (d *decoder) readByte() (byte, error) {
	if d.pos >= len(d.data) {
		return 0, io.ErrUnexpectedEOF
	}
	b := d.data[d.pos]
	d.pos++
	return b, nil
}

// decodeUint decodes an unsigned integer from the gob stream.
// Values 0–127 are represented directly as a single byte.
// Larger values are preceded by a byte whose bitwise complement
// indicates how many big-endian data bytes follow.
func (d *decoder) decodeUint() (uint64, error) {
	b, err := d.readByte()
	if err != nil {
		return 0, err
	}
	if b <= 0x7F {
		return uint64(b), nil
	}
	// The complement of the leading byte gives the data byte count.
	n := int(^b)
	if n < 0 || n > 8 {
		return 0, fmt.Errorf("invalid uint byte count: %d from 0x%02x", n, b)
	}
	var val uint64
	for i := 0; i < n; i++ {
		bv, err := d.readByte()
		if err != nil {
			return 0, err
		}
		val = (val << 8) | uint64(bv)
	}
	return val, nil
}

// decodeInt decodes a signed integer. The unsigned representation
// carries the magnitude in bits 1+ and a sign indicator in bit 0.
func (d *decoder) decodeInt() (int64, error) {
	u, err := d.decodeUint()
	if err != nil {
		return 0, err
	}
	if u&1 != 0 {
		return -int64(u >> 1), nil
	}
	return int64(u >> 1), nil
}

// decodeFloat decodes a float64 stored as IEEE 754 bits
// within an unsigned integer.
func (d *decoder) decodeFloat() (float64, error) {
	u, err := d.decodeUint()
	if err != nil {
		return 0, err
	}
	if u == 0 {
		return 0, nil
	}
	return math.Float64frombits(u), nil
}

// decodeString decodes a length-prefixed UTF-8 string.
func (d *decoder) decodeString() (string, error) {
	n, err := d.decodeUint()
	if err != nil {
		return "", err
	}
	if d.pos+int(n) > len(d.data) {
		return "", io.ErrUnexpectedEOF
	}
	s := string(d.data[d.pos : d.pos+int(n)])
	d.pos += int(n)
	return s, nil
}

// decodeBytes decodes a byte slice.
func (d *decoder) decodeBytes() ([]byte, error) {
	n, err := d.decodeUint()
	if err != nil {
		return nil, err
	}
	if d.pos+int(n) > len(d.data) {
		return nil, io.ErrUnexpectedEOF
	}
	b := make([]byte, n)
	copy(b, d.data[d.pos:d.pos+int(n)])
	d.pos += int(n)
	return b, nil
}

// skipValue discards an encoded value from the stream.
func (d *decoder) skipValue() error {
	_, err := d.decodeUint()
	return err
}

// decodeWireType reads a wireType descriptor from the stream.
// wireType fields: ArrayT(0), SliceT(1), StructT(2), MapT(3),
// followed by GobEncoderT(4), BinaryMarshalerT(5), TextMarshalerT(6).
func (d *decoder) decodeWireType() (*typeDef, error) {
	td := &typeDef{}
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return nil, err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			if err := d.decodeArrayType(td); err != nil {
				return nil, err
			}
		case 1:
			if err := d.decodeSliceType(td); err != nil {
				return nil, err
			}
		case 2:
			if err := d.decodeStructType(td); err != nil {
				return nil, err
			}
		case 3:
			if err := d.decodeMapType(td); err != nil {
				return nil, err
			}
		default:
			// GobEncoderT / BinaryMarshalerT / TextMarshalerT — skip.
			if err := d.skipValue(); err != nil {
				return nil, err
			}
		}
	}
	return td, nil
}

// decodeCommonType reads CommonType { Name string; Id int }.
func (d *decoder) decodeCommonType(td *typeDef) error {
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			name, err := d.decodeString()
			if err != nil {
				return err
			}
			td.Name = name
		case 1:
			id, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.ID = int(id)
		default:
			if err := d.skipValue(); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d *decoder) decodeStructType(td *typeDef) error {
	td.Kind = kindStruct
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			if err := d.decodeCommonType(td); err != nil {
				return err
			}
		case 1:
			nf, err := d.decodeUint()
			if err != nil {
				return err
			}
			for i := 0; i < int(nf); i++ {
				ft, err := d.decodeFieldType()
				if err != nil {
					return err
				}
				td.Fields = append(td.Fields, ft)
			}
		default:
			if err := d.skipValue(); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d *decoder) decodeFieldType() (fieldDef, error) {
	var f fieldDef
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return f, err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			name, err := d.decodeString()
			if err != nil {
				return f, err
			}
			f.Name = name
		case 1:
			id, err := d.decodeInt()
			if err != nil {
				return f, err
			}
			f.TypeID = int(id)
		default:
			if err := d.skipValue(); err != nil {
				return f, err
			}
		}
	}
	return f, nil
}

func (d *decoder) decodeArrayType(td *typeDef) error {
	td.Kind = kindArray
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			if err := d.decodeCommonType(td); err != nil {
				return err
			}
		case 1:
			id, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.Elem = int(id)
		case 2:
			l, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.Len = int(l)
		default:
			if err := d.skipValue(); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d *decoder) decodeSliceType(td *typeDef) error {
	td.Kind = kindSlice
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			if err := d.decodeCommonType(td); err != nil {
				return err
			}
		case 1:
			id, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.Elem = int(id)
		default:
			if err := d.skipValue(); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d *decoder) decodeMapType(td *typeDef) error {
	td.Kind = kindMap
	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		switch fieldNum {
		case 0:
			if err := d.decodeCommonType(td); err != nil {
				return err
			}
		case 1:
			id, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.Key = int(id)
		case 2:
			id, err := d.decodeInt()
			if err != nil {
				return err
			}
			td.Elem = int(id)
		default:
			if err := d.skipValue(); err != nil {
				return err
			}
		}
	}
	return nil
}

// decodeValue decodes a value of the given type ID and returns it
// as an interface{} suitable for JSON marshaling.
func (d *decoder) decodeValue(typeID int) (interface{}, error) {
	switch typeID {
	case tidBool:
		v, err := d.decodeUint()
		if err != nil {
			return nil, err
		}
		return v != 0, nil

	case tidInt:
		v, err := d.decodeInt()
		if err != nil {
			return nil, err
		}
		return float64(v), nil

	case tidUint:
		v, err := d.decodeUint()
		if err != nil {
			return nil, err
		}
		return float64(v), nil

	case tidFloat:
		v, err := d.decodeFloat()
		if err != nil {
			return nil, err
		}
		if math.IsNaN(v) {
			return "NaN", nil
		}
		if math.IsInf(v, 1) {
			return "+Inf", nil
		}
		if math.IsInf(v, -1) {
			return "-Inf", nil
		}
		return v, nil

	case tidBytes:
		b, err := d.decodeBytes()
		if err != nil {
			return nil, err
		}
		return base64.StdEncoding.EncodeToString(b), nil

	case tidString:
		return d.decodeString()

	case tidComplex:
		re, err := d.decodeFloat()
		if err != nil {
			return nil, err
		}
		im, err := d.decodeFloat()
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"Re": re, "Im": im}, nil
	}

	// User-defined type
	td, ok := d.types[typeID]
	if !ok {
		return nil, fmt.Errorf("unknown type ID %d", typeID)
	}

	switch td.Kind {
	case kindStruct:
		return d.decodeStructValue(td)
	case kindArray:
		return d.decodeArrayValue(td)
	case kindSlice:
		return d.decodeSliceValue(td)
	case kindMap:
		return d.decodeMapValue(td)
	}
	return nil, fmt.Errorf("unsupported type kind %d", td.Kind)
}

func (d *decoder) decodeStructValue(td *typeDef) (interface{}, error) {
	result := make(map[string]interface{})
	// Fill all fields with their zero values so omitted fields
	// still appear in the JSON output.
	for _, f := range td.Fields {
		result[f.Name] = zeroValue(f.TypeID)
	}

	fieldNum := -1
	for {
		delta, err := d.decodeUint()
		if err != nil {
			return nil, err
		}
		if delta == 0 {
			break
		}
		fieldNum += int(delta)
		if fieldNum >= len(td.Fields) {
			return nil, fmt.Errorf("field %d out of range for %s (%d fields)",
				fieldNum, td.Name, len(td.Fields))
		}
		f := td.Fields[fieldNum]
		val, err := d.decodeValue(f.TypeID)
		if err != nil {
			return nil, err
		}
		result[f.Name] = val
	}
	return result, nil
}

func (d *decoder) decodeArrayValue(td *typeDef) (interface{}, error) {
	n, err := d.decodeUint()
	if err != nil {
		return nil, err
	}
	result := make([]interface{}, n)
	for i := 0; i < int(n); i++ {
		v, err := d.decodeValue(td.Elem)
		if err != nil {
			return nil, err
		}
		result[i] = v
	}
	return result, nil
}

func (d *decoder) decodeSliceValue(td *typeDef) (interface{}, error) {
	return d.decodeArrayValue(td)
}

func (d *decoder) decodeMapValue(td *typeDef) (interface{}, error) {
	n, err := d.decodeUint()
	if err != nil {
		return nil, err
	}
	result := make(map[string]interface{})
	for i := 0; i < int(n); i++ {
		key, err := d.decodeValue(td.Key)
		if err != nil {
			return nil, err
		}
		val, err := d.decodeValue(td.Elem)
		if err != nil {
			return nil, err
		}
		result[toStringKey(key)] = val
	}
	return result, nil
}

func toStringKey(v interface{}) string {
	switch k := v.(type) {
	case string:
		return k
	case float64:
		return strconv.FormatFloat(k, 'g', -1, 64)
	case bool:
		if k {
			return "true"
		}
		return "false"
	default:
		return fmt.Sprintf("%v", v)
	}
}

// zeroValue returns the JSON-appropriate zero value for a type.
func zeroValue(typeID int) interface{} {
	switch typeID {
	case tidBool:
		return false
	case tidInt, tidUint:
		return float64(0)
	case tidFloat:
		return float64(0)
	case tidString:
		return ""
	case tidBytes:
		return ""
	case tidComplex:
		return map[string]interface{}{"Re": float64(0), "Im": float64(0)}
	}
	return nil
}

// decodeMessage reads one delimited message from the stream.
// Messages alternate between type definitions (negative type IDs)
// and typed values (positive type IDs).
func (d *decoder) decodeMessage() (interface{}, error) {
	msgLen, err := d.decodeUint()
	if err != nil {
		return nil, err
	}
	if msgLen == 0 {
		return nil, io.ErrUnexpectedEOF
	}
	msgEnd := d.pos + int(msgLen)
	if msgEnd > len(d.data) {
		return nil, io.ErrUnexpectedEOF
	}

	typeID, err := d.decodeInt()
	if err != nil {
		return nil, err
	}

	if typeID < 0 {
		// Type definition message.
		defTypeID := int(-typeID)
		td, err := d.decodeWireType()
		if err != nil {
			return nil, err
		}
		if td.ID == 0 {
			td.ID = defTypeID
		}
		d.types[td.ID] = td
		d.pos = msgEnd
		return d.decodeMessage()
	}

	tid := int(typeID)

	// Predefined scalar types are sent as singleton-wrapped values
	// (a synthetic one-field struct with delta 0).
	if tid >= tidBool && tid <= tidInterface {
		delta, err := d.decodeUint()
		if err != nil {
			return nil, err
		}
		if delta != 0 {
			return nil, fmt.Errorf("expected singleton delta 0, got %d", delta)
		}
		val, err := d.decodeValue(tid)
		if err != nil {
			return nil, err
		}
		d.pos = msgEnd
		return val, nil
	}

	// User-defined type — decode the value directly.
	val, err := d.decodeValue(tid)
	if err != nil {
		return nil, err
	}
	d.pos = msgEnd
	return val, nil
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read error: %v\n", err)
		os.Exit(1)
	}

	d := newDecoder(data)
	var results []interface{}

	for d.remaining() > 0 {
		val, err := d.decodeMessage()
		if err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				break
			}
			fmt.Fprintf(os.Stderr, "decode error at pos %d: %v\n", d.pos, err)
			os.Exit(1)
		}
		results = append(results, val)
	}

	out, err := json.Marshal(results)
	if err != nil {
		fmt.Fprintf(os.Stderr, "json error: %v\n", err)
		os.Exit(1)
	}
	fmt.Print(string(out))
}
