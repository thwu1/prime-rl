package main

import (
	"encoding/hex"
	"fmt"
	"math"
	"sort"
)

// Decode decodes protobuf binary data using the given schema.
func Decode(schema *Schema, data []byte) (map[string]interface{}, error) {
	result := make(map[string]interface{})
	pos := 0

	for pos < len(data) {
		fieldNum, wireType, n, err := DecodeTag(data[pos:])
		if err != nil {
			return nil, fmt.Errorf("decoding tag at offset %d: %w", pos, err)
		}
		pos += n

		field := schema.FieldByNumber(fieldNum)
		if field == nil {
			skipN, err := skipField(wireType, data[pos:])
			if err != nil {
				return nil, fmt.Errorf("skipping unknown field %d: %w", fieldNum, err)
			}
			pos += skipN
			continue
		}

		// Handle packed repeated fields arriving as LEN records.
		if field.Repeated && field.Packed && wireType == WireLengthDelim && isPackable(field.Type) {
			payload, payloadN, err := DecodeBytes(data[pos:])
			if err != nil {
				return nil, fmt.Errorf("decoding packed field %s: %w", field.Name, err)
			}
			pos += payloadN

			vals, err := decodePackedValues(field, payload)
			if err != nil {
				return nil, fmt.Errorf("decoding packed values for %s: %w", field.Name, err)
			}

			existing, ok := result[field.Name]
			if !ok {
				result[field.Name] = vals
			} else {
				result[field.Name] = append(existing.([]interface{}), vals...)
			}
			continue
		}

		val, consumed, err := decodeFieldValue(field, wireType, data[pos:])
		if err != nil {
			return nil, fmt.Errorf("decoding field %s (number %d): %w", field.Name, field.Number, err)
		}
		pos += consumed

		if field.Repeated {
			existing, ok := result[field.Name]
			if !ok {
				result[field.Name] = []interface{}{val}
			} else {
				result[field.Name] = append(existing.([]interface{}), val)
			}
		} else {
			result[field.Name] = val
		}
	}

	return result, nil
}

func decodePackedValues(field *Field, payload []byte) ([]interface{}, error) {
	if len(payload) == 0 {
		return nil, nil
	}
	v, _, err := DecodeVarint(payload)
	if err != nil {
		return nil, err
	}
	return []interface{}{interpretVarint(field, v)}, nil
}

func decodeFieldValue(field *Field, wireType int, data []byte) (interface{}, int, error) {
	switch wireType {
	case WireVarint:
		v, n, err := DecodeVarint(data)
		if err != nil {
			return nil, 0, err
		}
		return interpretVarint(field, v), n, nil

	case WireFixed32:
		v, n, err := DecodeFixed32(data)
		if err != nil {
			return nil, 0, err
		}
		return interpretFixed32(field, v), n, nil

	case WireFixed64:
		v, n, err := DecodeFixed64(data)
		if err != nil {
			return nil, 0, err
		}
		return interpretFixed64(field, v), n, nil

	case WireLengthDelim:
		payload, n, err := DecodeBytes(data)
		if err != nil {
			return nil, 0, err
		}

		if field.Type == TypeMessage && field.Schema != nil {
			msg, err := Decode(field.Schema, payload)
			if err != nil {
				return nil, 0, fmt.Errorf("decoding submessage: %w", err)
			}
			return msg, n, nil
		}

		if field.Type == TypeString {
			return string(payload), n, nil
		}

		if field.Type == TypeBytes {
			return hex.EncodeToString(payload), n, nil
		}

		return hex.EncodeToString(payload), n, nil

	case WireStartGroup:
		return nil, 0, fmt.Errorf("wire type SGROUP not implemented")

	case WireEndGroup:
		return nil, 0, ErrBadGroup

	default:
		return nil, 0, fmt.Errorf("%w: %d", ErrInvalidWire, wireType)
	}
}

func interpretVarint(field *Field, v uint64) interface{} {
	switch field.Type {
	case TypeBool:
		return v != 0
	case TypeInt32:
		return int64(int32(v))
	case TypeInt64:
		return int64(v)
	case TypeUint32, TypeUint64, TypeEnum:
		return v
	case TypeSint32:
		return int64(int32(DecodeZigZag(v)))
	case TypeSint64:
		return DecodeZigZag(v)
	default:
		return v
	}
}

func interpretFixed32(field *Field, v uint32) interface{} {
	switch field.Type {
	case TypeFloat:
		return float64(math.Float32frombits(v))
	case TypeSfixed32:
		return int64(int32(v))
	default:
		return uint64(v)
	}
}

func interpretFixed64(field *Field, v uint64) interface{} {
	switch field.Type {
	case TypeDouble:
		return math.Float64frombits(v)
	case TypeSfixed64:
		return int64(v)
	default:
		return v
	}
}

func skipField(wireType int, data []byte) (int, error) {
	switch wireType {
	case WireVarint:
		_, n, err := DecodeVarint(data)
		return n, err
	case WireFixed32:
		if len(data) < 4 {
			return 0, ErrTruncated
		}
		return 4, nil
	case WireFixed64:
		if len(data) < 8 {
			return 0, ErrTruncated
		}
		return 8, nil
	case WireLengthDelim:
		_, n, err := DecodeBytes(data)
		return n, err
	case WireStartGroup:
		return skipGroup(data)
	case WireEndGroup:
		return 0, ErrBadGroup
	default:
		return 0, fmt.Errorf("%w: %d", ErrInvalidWire, wireType)
	}
}

func skipGroup(data []byte) (int, error) {
	return 0, fmt.Errorf("cannot skip groups")
}

// Encode encodes a map of values into protobuf binary format using the schema.
func Encode(schema *Schema, values map[string]interface{}) ([]byte, error) {
	var result []byte

	fields := make([]Field, len(schema.Fields))
	copy(fields, schema.Fields)
	sort.Slice(fields, func(i, j int) bool {
		return fields[i].Number < fields[j].Number
	})

	for _, field := range fields {
		val, ok := values[field.Name]
		if !ok {
			continue
		}

		if field.Repeated {
			arr, ok := val.([]interface{})
			if !ok {
				return nil, fmt.Errorf("field %s: expected array", field.Name)
			}

			if field.Packed && isPackable(field.Type) {
				encoded, err := encodePacked(&field, arr)
				if err != nil {
					return nil, err
				}
				result = append(result, EncodeTag(field.Number, WireLengthDelim)...)
				result = append(result, EncodeBytes(encoded)...)
			} else {
				for _, item := range arr {
					encoded, err := encodeFieldValue(&field, item)
					if err != nil {
						return nil, err
					}
					wt := field.WireType()
					result = append(result, EncodeTag(field.Number, wt)...)
					if wt == WireLengthDelim {
						result = append(result, EncodeBytes(encoded)...)
					} else {
						result = append(result, encoded...)
					}
				}
			}
		} else if field.Type == TypeGroup {
			return nil, fmt.Errorf("group encoding not supported")
		} else {
			encoded, err := encodeFieldValue(&field, val)
			if err != nil {
				return nil, err
			}
			wt := field.WireType()
			result = append(result, EncodeTag(field.Number, wt)...)
			if wt == WireLengthDelim {
				result = append(result, EncodeBytes(encoded)...)
			} else {
				result = append(result, encoded...)
			}
		}
	}

	return result, nil
}

func encodeFieldValue(field *Field, val interface{}) ([]byte, error) {
	switch field.Type {
	case TypeBool:
		b, ok := val.(bool)
		if !ok {
			return nil, fmt.Errorf("field %s: expected bool", field.Name)
		}
		if b {
			return EncodeVarint(1), nil
		}
		return EncodeVarint(0), nil

	case TypeInt32, TypeInt64:
		n, err := toInt64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeVarint(uint64(n)), nil

	case TypeUint32, TypeUint64, TypeEnum:
		n, err := toUint64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeVarint(n), nil

	case TypeSint32, TypeSint64:
		n, err := toInt64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeVarint(EncodeZigZag(n)), nil

	case TypeFixed32, TypeSfixed32:
		n, err := toUint64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeFixed32(uint32(n)), nil

	case TypeFixed64, TypeSfixed64:
		n, err := toUint64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeFixed64(n), nil

	case TypeFloat:
		f, err := toFloat64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeFloat32(float32(f)), nil

	case TypeDouble:
		f, err := toFloat64(val)
		if err != nil {
			return nil, fmt.Errorf("field %s: %w", field.Name, err)
		}
		return EncodeFloat64(f), nil

	case TypeString:
		s, ok := val.(string)
		if !ok {
			return nil, fmt.Errorf("field %s: expected string", field.Name)
		}
		return []byte(s), nil

	case TypeBytes:
		s, ok := val.(string)
		if !ok {
			return nil, fmt.Errorf("field %s: expected hex string", field.Name)
		}
		b, err := hex.DecodeString(s)
		if err != nil {
			return nil, fmt.Errorf("field %s: invalid hex: %w", field.Name, err)
		}
		return b, nil

	case TypeMessage:
		m, ok := val.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("field %s: expected object", field.Name)
		}
		if field.Schema == nil {
			return nil, fmt.Errorf("field %s: no schema for message", field.Name)
		}
		return Encode(field.Schema, m)

	default:
		return nil, fmt.Errorf("unsupported type: %s", field.Type)
	}
}

func encodePacked(field *Field, values []interface{}) ([]byte, error) {
	var result []byte
	for _, val := range values {
		encoded, err := encodeFieldValue(field, val)
		if err != nil {
			return nil, err
		}
		result = append(result, encoded...)
	}
	return result, nil
}

func isPackable(t FieldType) bool {
	switch t {
	case TypeInt32, TypeInt64, TypeUint32, TypeUint64,
		TypeSint32, TypeSint64, TypeBool, TypeEnum,
		TypeFixed32, TypeFixed64, TypeSfixed32, TypeSfixed64,
		TypeFloat, TypeDouble:
		return true
	default:
		return false
	}
}

func toInt64(v interface{}) (int64, error) {
	switch n := v.(type) {
	case float64:
		return int64(n), nil
	case int64:
		return n, nil
	case int:
		return int64(n), nil
	default:
		return 0, fmt.Errorf("expected number, got %T", v)
	}
}

func toUint64(v interface{}) (uint64, error) {
	switch n := v.(type) {
	case float64:
		return uint64(n), nil
	case uint64:
		return n, nil
	case int64:
		return uint64(n), nil
	case int:
		return uint64(n), nil
	default:
		return 0, fmt.Errorf("expected number, got %T", v)
	}
}

func toFloat64(v interface{}) (float64, error) {
	switch n := v.(type) {
	case float64:
		return n, nil
	case int64:
		return float64(n), nil
	case int:
		return float64(n), nil
	default:
		return 0, fmt.Errorf("expected number, got %T", v)
	}
}
