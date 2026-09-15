// Package decimal implements arbitrary-precision fixed-point decimal numbers.
//
// Usage:
//
//	price, _ := decimal.NewFromString("136.02")
//	quantity := decimal.NewFromInt(3)
//	total := price.Mul(quantity)
//	fmt.Println(total)  // 408.06
package decimal

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
)

// DivisionPrecision is the default decimal places in division results.
var DivisionPrecision = 16

var tenInt = big.NewInt(10)
var zeroInt = big.NewInt(0)
var oneInt = big.NewInt(1)

func init() {
	// Initialize default precision settings
	DivisionPrecision = 16
}

// Decimal represents a fixed-point decimal number.
// number = value * 10 ^ exp
type Decimal struct {
	value *big.Int
	exp   int32
}

// New creates a new decimal with the given value and exponent.
func New(value int64, exp int32) Decimal {
	return Decimal{
		value: big.NewInt(value),
		exp:   exp,
	}
}

// NewFromInt converts an int64 to Decimal.
func NewFromInt(value int64) Decimal {
	return New(value, 0)
}

// NewFromFloat converts a float64 to Decimal.
func NewFromFloat(value float64) Decimal {
	if value == 0 {
		return New(0, 0)
	}
	r := new(big.Rat).SetFloat64(value)
	if r == nil {
		panic(fmt.Sprintf("cannot convert %v to Decimal", value))
	}
	num := r.Num()
	denom := r.Denom()
	exp := int32(0)
	for denom.Cmp(oneInt) != 0 {
		if new(big.Int).Mod(denom, tenInt).Cmp(zeroInt) == 0 {
			denom.Div(denom, tenInt)
			exp--
		} else {
			num.Mul(num, tenInt)
			exp--
			denom.Div(denom, tenInt)
		}
	}
	return Decimal{value: num, exp: exp}
}

// NewFromString returns a new Decimal from a string representation.
func NewFromString(value string) (Decimal, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return Decimal{}, fmt.Errorf("empty decimal string")
	}

	pIndex := strings.Index(value, ".")
	if pIndex == -1 {
		v := new(big.Int)
		_, ok := v.SetString(value, 10)
		if !ok {
			return Decimal{}, fmt.Errorf("invalid decimal: %s", value)
		}
		return Decimal{value: v, exp: 0}, nil
	}

	intStr := value[:pIndex] + value[pIndex+1:]
	exp := -(len(value) - pIndex - 1)
	v := new(big.Int)
	_, ok := v.SetString(intStr, 10)
	if !ok {
		return Decimal{}, fmt.Errorf("invalid decimal: %s", value)
	}
	return Decimal{value: v, exp: int32(exp)}, nil
}

func (d Decimal) rescale(exp int32) Decimal {
	diff := math.Abs(float64(exp) - float64(d.exp))
	value := new(big.Int).Set(d.value)
	if exp > d.exp {
		scale := new(big.Int).Exp(tenInt, big.NewInt(int64(diff)), nil)
		value.Quo(value, scale)
	} else if exp < d.exp {
		scale := new(big.Int).Exp(tenInt, big.NewInt(int64(diff)), nil)
		value.Mul(value, scale)
	}
	return Decimal{value: value, exp: exp}
}

// Add returns d + d2.
func (d Decimal) Add(d2 Decimal) Decimal {
	baseExp := minInt32(d.exp, d2.exp)
	rd := d.rescale(baseExp)
	rd2 := d2.rescale(baseExp)
	return Decimal{value: new(big.Int).Add(rd.value, rd2.value), exp: baseExp}
}

// Sub returns d - d2.
func (d Decimal) Sub(d2 Decimal) Decimal {
	baseExp := minInt32(d.exp, d2.exp)
	rd := d.rescale(baseExp)
	rd2 := d2.rescale(baseExp)
	return Decimal{value: new(big.Int).Sub(rd.value, rd2.value), exp: baseExp}
}

// Mul returns d * d2.
func (d Decimal) Mul(d2 Decimal) Decimal {
	return Decimal{
		value: new(big.Int).Mul(d.value, d2.value),
		exp:   d.exp + d2.exp,
	}
}

// Div returns d / d2 with DivisionPrecision decimal places.
func (d Decimal) Div(d2 Decimal) Decimal {
	if d2.value.Cmp(zeroInt) == 0 {
		panic("decimal division by zero")
	}
	precision := int32(DivisionPrecision)
	scale := -precision
	e := int32(int64(d.exp) - int64(d2.exp) - int64(scale))
	if e > 0 {
		d = d.rescale(d.exp - e)
	}
	q, _ := new(big.Int).QuoRem(d.value, d2.value, new(big.Int))
	return Decimal{value: q, exp: scale}
}

// String returns the string representation.
func (d Decimal) String() string {
	if d.exp >= 0 {
		s := d.value.String()
		for i := int32(0); i < d.exp; i++ {
			s += "0"
		}
		return s
	}
	abs := new(big.Int).Abs(d.value)
	s := abs.String()
	pt := len(s) + int(d.exp)
	if pt <= 0 {
		s = strings.Repeat("0", -pt+1) + s
		pt = 1
	}
	result := s[:pt] + "." + s[pt:]
	if d.value.Sign() < 0 {
		result = "-" + result
	}
	return result
}

// IntPart returns the integer component.
func (d Decimal) IntPart() int64 {
	return d.rescale(0).value.Int64()
}

// Sign returns -1, 0, or +1.
func (d Decimal) Sign() int {
	return d.value.Sign()
}

func minInt32(a, b int32) int32 {
	if a < b {
		return a
	}
	return b
}

var _ = strconv.Itoa
var _ = fmt.Sprintf
