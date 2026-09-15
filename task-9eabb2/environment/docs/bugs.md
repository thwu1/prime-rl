# Known Vulnerabilities in libmfp

Four vulnerabilities have been identified in the libmfp binary format parser.
Each requires a MAGMA-compatible ground-truth instrumentation patch.

---

## MFP001 — Integer Truncation in Data Normalization

**Severity:** High  
**Affected function:** `mfp_normalize()`  
**CVE analog:** CVE-2018-13785 (libpng integer overflow in row_factor computation)

When computing a scaled buffer size for data normalization, a 64-bit intermediate
product is truncated to 32 bits during assignment. If the product of the entry's
`data_len` and the document's `version` (used as scale factor) exceeds `UINT32_MAX`,
the allocated buffer is undersized. The subsequent write loop uses the full
(non-truncated) iteration count, resulting in a heap buffer overflow.

---

## MFP002 — Missing Bounds Check in Entry Name Parsing

**Severity:** High  
**Affected function:** `mfp_parse()`  
**CVE analog:** CVE-2016-2108 (OpenSSL ASN.1 negative zero encoding buffer overread)

When parsing entry names from the input buffer, the `name_len` field read from
the binary format is used directly as a byte count for `memcpy` without first
verifying that the input buffer contains that many remaining bytes. A crafted
input with `name_len` exceeding the available data causes a read past the end
of the allocated input buffer.

---

## MFP003 — Off-by-One Error in Entry Parsing Loop

**Severity:** Medium  
**Affected function:** `mfp_parse()`  
**CVE analog:** CVE-2019-6706 (Lua off-by-one in vararg boundary check)

The loop that iterates over document entries uses an inclusive upper-bound
comparison where an exclusive comparison is required. This causes the loop body
to execute one additional iteration, writing entry data to a memory location
beyond the bounds of the allocated entry array. The result is a heap buffer
overflow that corrupts adjacent heap metadata.

---

## MFP004 — Division by Zero in Summary Rendering

**Severity:** Medium  
**Affected function:** `mfp_render_summary()`  
**CVE analog:** CVE-2019-9631 (Poppler division by zero in CairoRescaleBox)

When computing the average value of entry data bytes, the code divides the
accumulated sum by the entry's `type` field without checking for a zero value.
Processing an entry with `type == 0` causes a `SIGFPE` (floating-point exception /
arithmetic signal), terminating the process.
