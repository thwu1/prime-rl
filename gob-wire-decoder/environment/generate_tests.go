// generate_tests.go — builds gob test fixtures under /app/testdata/
// Build: go run /app/generate_tests.go
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/gob"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
)


var fixtureCount int

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func writeFixture(name string, gobBytes []byte, jsonValue interface{}) {
	dir := "/app/testdata"
	must(os.MkdirAll(dir, 0755))
	must(os.WriteFile(filepath.Join(dir, name+".gob"), gobBytes, 0644))
	jb, err := json.Marshal(jsonValue)
	must(err)
	var buf bytes.Buffer
	must(json.Compact(&buf, jb))
	must(os.WriteFile(filepath.Join(dir, name+".json"), buf.Bytes(), 0644))
	fixtureCount++
}

type M = map[string]interface{}
type A = []interface{}

func main() {
	// Register types needed for interface encoding
	gob.Register(0)

	// Test 01: Simple struct with ints
	{
		type Point struct{ X, Y int }
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Point{22, 33}))
		expected := A{M{"X": float64(22), "Y": float64(33)}}
		writeFixture("01_point", buf.Bytes(), expected)
	}

	// Test 02: Scalar int (singleton, non-struct top-level)
	{
		var buf bytes.Buffer
		val := 42
		must(gob.NewEncoder(&buf).Encode(val))
		expected := A{float64(42)}
		writeFixture("02_int", buf.Bytes(), expected)
	}

	// Test 03: String top-level
	{
		var buf bytes.Buffer
		val := "hello, gobs!"
		must(gob.NewEncoder(&buf).Encode(val))
		expected := A{"hello, gobs!"}
		writeFixture("03_string", buf.Bytes(), expected)
	}

	// Test 04: Bool top-level
	{
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(true))
		expected := A{true}
		writeFixture("04_bool", buf.Bytes(), expected)
	}

	// Test 05: Float64 top-level
	{
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(17.0))
		expected := A{float64(17)}
		writeFixture("05_float", buf.Bytes(), expected)
	}

	// Test 06: Negative int
	{
		var buf bytes.Buffer
		val := -129
		must(gob.NewEncoder(&buf).Encode(val))
		expected := A{float64(-129)}
		writeFixture("06_negint", buf.Bytes(), expected)
	}

	// Test 07: Struct with mixed types
	{
		type Record struct {
			Name   string
			Age    int
			Score  float64
			Active bool
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Record{"Alice", 30, 95.5, true}))
		expected := A{M{"Name": "Alice", "Age": float64(30), "Score": 95.5, "Active": true}}
		writeFixture("07_mixed_struct", buf.Bytes(), expected)
	}

	// Test 08: Slice of ints
	{
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode([]int{10, 20, 30}))
		expected := A{A{float64(10), float64(20), float64(30)}}
		writeFixture("08_slice_int", buf.Bytes(), expected)
	}

	// Test 09: Map[string]int
	{
		var buf bytes.Buffer
		m := map[string]int{"alpha": 1, "beta": 2}
		must(gob.NewEncoder(&buf).Encode(m))
		expected := A{M{"alpha": float64(1), "beta": float64(2)}}
		writeFixture("09_map", buf.Bytes(), expected)
	}

	// Test 10: Nested struct (2 levels)
	{
		type Inner struct {
			V int
		}
		type Outer struct {
			Label string
			Data  Inner
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Outer{"test", Inner{99}}))
		expected := A{M{"Label": "test", "Data": M{"V": float64(99)}}}
		writeFixture("10_nested", buf.Bytes(), expected)
	}

	// Test 11: []byte (base64 in JSON)
	{
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode([]byte{0xDE, 0xAD, 0xBE, 0xEF}))
		expected := A{base64.StdEncoding.EncodeToString([]byte{0xDE, 0xAD, 0xBE, 0xEF})}
		writeFixture("11_bytes", buf.Bytes(), expected)
	}

	// Test 12: Uint top-level
	{
		var buf bytes.Buffer
		val := uint(256)
		must(gob.NewEncoder(&buf).Encode(val))
		expected := A{float64(256)}
		writeFixture("12_uint", buf.Bytes(), expected)
	}

	// Test 13: Zero-value fields omitted in wire format
	{
		type Sparse struct {
			A int
			B string
			C float64
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Sparse{A: 0, B: "", C: 3.14}))
		expected := A{M{"A": float64(0), "B": "", "C": 3.14}}
		writeFixture("13_sparse", buf.Bytes(), expected)
	}

	// Test 14: Multi-value stream (two values same type)
	{
		type Pair struct{ X, Y int }
		var buf bytes.Buffer
		enc := gob.NewEncoder(&buf)
		must(enc.Encode(Pair{1, 2}))
		must(enc.Encode(Pair{3, 4}))
		expected := A{
			M{"X": float64(1), "Y": float64(2)},
			M{"X": float64(3), "Y": float64(4)},
		}
		writeFixture("14_multi", buf.Bytes(), expected)
	}

	// Test 15: Large integer
	{
		var buf bytes.Buffer
		val := int64(1 << 40)
		must(gob.NewEncoder(&buf).Encode(val))
		expected := A{float64(1 << 40)}
		writeFixture("15_large_int", buf.Bytes(), expected)
	}

	// Test 16: Struct with slice field
	{
		type WithSlice struct {
			Name  string
			Items []int
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(WithSlice{"list", []int{5, 10, 15}}))
		expected := A{M{"Name": "list", "Items": A{float64(5), float64(10), float64(15)}}}
		writeFixture("16_struct_slice", buf.Bytes(), expected)
	}

	// Test 17: Special float values (NaN, +Inf, -Inf)
	{
		type Floats struct {
			PosInf float64
			NegInf float64
			Nan    float64
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Floats{math.Inf(1), math.Inf(-1), math.NaN()}))
		expected := A{M{"PosInf": "+Inf", "NegInf": "-Inf", "Nan": "NaN"}}
		writeFixture("17_special_floats", buf.Bytes(), expected)
	}

	// Test 18: Array (fixed size)
	{
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode([3]int{100, 200, 300}))
		expected := A{A{float64(100), float64(200), float64(300)}}
		writeFixture("18_array", buf.Bytes(), expected)
	}

	// Test 19: Complex number
	{
		type Cpx struct {
			C complex128
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Cpx{complex(17, 19)}))
		expected := A{M{"C": M{"Re": float64(17), "Im": float64(19)}}}
		writeFixture("19_complex", buf.Bytes(), expected)
	}

	// Test 20: Empty struct
	{
		type Empty struct{}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Empty{}))
		expected := A{M{}}
		writeFixture("20_empty_struct", buf.Bytes(), expected)
	}

	// Test 21: Multi-value stream with two sequential ints
	{
		var buf bytes.Buffer
		enc := gob.NewEncoder(&buf)
		val1 := 42
		val2 := -100
		must(enc.Encode(val1))
		must(enc.Encode(val2))
		expected := A{float64(42), float64(-100)}
		writeFixture("21_multi_int", buf.Bytes(), expected)
	}

	// Test 22: Multi-type stream (two different struct types)
	{
		type Alpha struct{ A int }
		type Beta struct {
			B string
			C float64
		}
		var buf bytes.Buffer
		enc := gob.NewEncoder(&buf)
		must(enc.Encode(Alpha{10}))
		must(enc.Encode(Beta{"hi", 3.14}))
		expected := A{
			M{"A": float64(10)},
			M{"B": "hi", "C": 3.14},
		}
		writeFixture("22_multi_type", buf.Bytes(), expected)
	}

	// Test 23: Deeply nested struct (3 levels)
	{
		type Level3 struct{ Val int }
		type Level2 struct {
			Sub Level3
			Tag string
		}
		type Level1 struct {
			Inner Level2
			Name  string
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Level1{
			Inner: Level2{Sub: Level3{Val: 42}, Tag: "x"},
			Name:  "top",
		}))
		expected := A{M{
			"Inner": M{
				"Sub": M{"Val": float64(42)},
				"Tag": "x",
			},
			"Name": "top",
		}}
		writeFixture("23_deep_nested", buf.Bytes(), expected)
	}

	// Test 24: Struct with all-zero nested struct (tests zero-value initialization)
	{
		type ZInner struct {
			X int
			Y string
		}
		type ZOuter struct {
			Data  ZInner
			Label string
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(ZOuter{Data: ZInner{}, Label: "test"}))
		expected := A{M{
			"Data":  M{"X": float64(0), "Y": ""},
			"Label": "test",
		}}
		writeFixture("24_zero_nested", buf.Bytes(), expected)
	}

	// Test 25: Slice of structs (tests singleton wrapping for user-defined non-struct types)
	{
		type SItem struct {
			Name string
			Qty  int
		}
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode([]SItem{
			{Name: "apple", Qty: 3},
			{Name: "banana", Qty: 5},
		}))
		expected := A{A{
			M{"Name": "apple", "Qty": float64(3)},
			M{"Name": "banana", "Qty": float64(5)},
		}}
		writeFixture("25_slice_structs", buf.Bytes(), expected)
	}

	// Test 26: Struct with interface field containing int (tests interface decoding)
	{
		type Boxed struct{ Val interface{} }
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(Boxed{Val: 42}))
		expected := A{M{"Val": float64(42)}}
		writeFixture("26_interface_int", buf.Bytes(), expected)
	}

	// Test 27: Struct with nil interface field
	{
		type NilBox struct{ Val interface{} }
		var buf bytes.Buffer
		must(gob.NewEncoder(&buf).Encode(NilBox{Val: nil}))
		expected := A{M{"Val": nil}}
		writeFixture("27_nil_interface", buf.Bytes(), expected)
	}

	fmt.Printf("Generated %d test fixtures in /app/testdata/\n", fixtureCount)
	if fixtureCount < 27 {
		fmt.Fprintf(os.Stderr, "ERROR: expected 27 fixtures, generated only %d\n", fixtureCount)
		os.Exit(1)
	}
}
