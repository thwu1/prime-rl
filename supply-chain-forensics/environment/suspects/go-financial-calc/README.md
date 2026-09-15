# go-financial-calc

Arbitrary-precision decimal numbers for Go financial calculations.

Fork of `shopspring/decimal` with improved rounding modes.

## Installation

```go
import "github.com/nicksprint/decimal"
```

## Usage

```go
price, _ := decimal.NewFromString("136.02")
quantity := decimal.NewFromInt(3)
total := price.Mul(quantity)
fmt.Println(total) // 408.06
```
