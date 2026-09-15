# Price Encoding

All price fields use a fixed-point integer representation where each unit
corresponds to 1e-9 (one billionth).

## Conversion

    price_float = price_raw / 1,000,000,000

For example, a raw value of `150250000000` represents a price of `$150.25`.

## Sentinel Value

The value `0x7FFFFFFFFFFFFFFF` (maximum signed 64-bit integer, 9223372036854775807)
is used as a sentinel to indicate an undefined or unavailable price. Records with
this price value should be treated specially depending on context.
