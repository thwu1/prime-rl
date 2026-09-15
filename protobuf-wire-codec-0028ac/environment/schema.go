package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// FieldType represents protobuf field types.
type FieldType string

const (
	TypeInt32    FieldType = "int32"
	TypeInt64    FieldType = "int64"
	TypeUint32   FieldType = "uint32"
	TypeUint64   FieldType = "uint64"
	TypeSint32   FieldType = "sint32"
	TypeSint64   FieldType = "sint64"
	TypeBool     FieldType = "bool"
	TypeEnum     FieldType = "enum"
	TypeFixed32  FieldType = "fixed32"
	TypeFixed64  FieldType = "fixed64"
	TypeSfixed32 FieldType = "sfixed32"
	TypeSfixed64 FieldType = "sfixed64"
	TypeFloat    FieldType = "float"
	TypeDouble   FieldType = "double"
	TypeString   FieldType = "string"
	TypeBytes    FieldType = "bytes"
	TypeMessage  FieldType = "message"
	TypeGroup    FieldType = "group"
)

// Schema represents a protobuf message schema.
type Schema struct {
	Name   string  `json:"name"`
	Fields []Field `json:"fields"`
}

// Field represents a single field in a schema.
type Field struct {
	Number   uint32    `json:"number"`
	Name     string    `json:"name"`
	Type     FieldType `json:"type"`
	Repeated bool      `json:"repeated"`
	Packed   bool      `json:"packed"`
	Schema   *Schema   `json:"schema,omitempty"`
}

// WireType returns the natural wire type for this field's type.
func (f *Field) WireType() int {
	switch f.Type {
	case TypeInt32, TypeInt64, TypeUint32, TypeUint64,
		TypeSint32, TypeSint64, TypeBool, TypeEnum:
		return WireVarint
	case TypeFixed64, TypeSfixed64, TypeDouble:
		return WireFixed64
	case TypeFixed32, TypeSfixed32, TypeFloat:
		return WireFixed32
	case TypeString, TypeBytes, TypeMessage:
		return WireLengthDelim
	case TypeGroup:
		return WireStartGroup
	default:
		return -1
	}
}

// FieldByNumber returns the field with the given number, or nil.
func (s *Schema) FieldByNumber(num uint32) *Field {
	for i := range s.Fields {
		if s.Fields[i].Number == num {
			return &s.Fields[i]
		}
	}
	return nil
}

// FieldByName returns the field with the given name, or nil.
func (s *Schema) FieldByName(name string) *Field {
	for i := range s.Fields {
		if s.Fields[i].Name == name {
			return &s.Fields[i]
		}
	}
	return nil
}

// LoadSchema loads a schema from a JSON file.
func LoadSchema(path string) (*Schema, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading schema: %w", err)
	}
	var schema Schema
	if err := json.Unmarshal(data, &schema); err != nil {
		return nil, fmt.Errorf("parsing schema: %w", err)
	}
	return &schema, nil
}
