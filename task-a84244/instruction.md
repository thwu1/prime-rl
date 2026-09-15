`/app/triint64.ml` implements 64-bit signed integer arithmetic using a three-limb representation (24-bit `lo`, 24-bit `mi`, 16-bit `hi`). The interface is in `/app/triint64.mli`; a differential test driver in `/app/main.ml` compares each operation against OCaml's native `Int64` and standard library.

The implementation contains multiple correctness defects across arithmetic, comparison, shifting, string conversion, hashing, serialization, and bit-counting. Some defects cascade through dependent operations; at least one causes the test driver to hang rather than produce output.

Fix `/app/triint64.ml` so that every operation matches the semantics below.

All operations listed in `/app/triint64.mli` must satisfy:

- Arithmetic (`add`, `sub`, `mul`, `neg`, `div`, `modulo`): match `Int64` equivalents for all inputs including `min_int` edge cases. `div` and `modulo` raise `Division_by_zero` for zero divisors.
- `compare`/`equal`: `compare` must agree in sign with `Int64.compare` for all pairs.
- Shifts (`shift_left`, `shift_right`, `shift_right_logical`): match `Int64` shift semantics for all shift counts 0-63 on all values, including negative numbers.
- `to_string`/`of_string`: match `Int64.to_string`/`Int64.of_string` for all representable values including `min_int`. `of_string` must handle `0x`/`0o`/`0b` prefixes and underscore separators.
- `to_hex`: match `Printf.sprintf "%Lx"` applied to the native value.
- `hash`: return the same value as `Hashtbl.hash` applied to the equivalent `Int64.t`.
- `marshal`/`unmarshal`: byte-identical to `Marshal.to_bytes`/`Marshal.from_bytes` applied to the equivalent `Int64.t`.
- `popcount`: number of set bits in the 64-bit two's complement representation.
- `clz`: number of leading zero bits (0 through 64).
- `rotate_left`: left-rotate within 64 bits, count taken modulo 64.

**Success:**

```
cd /app && dune build && dune exec ./main.exe
```

Exit code 0, stdout contains `ALL TESTS PASSED`.
