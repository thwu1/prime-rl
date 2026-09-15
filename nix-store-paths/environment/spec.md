# Nix Binary Cache Integrity Auditor — Specification

## 1. Narinfo File Format

Nix binary caches serve `.narinfo` files — plain-text key-value metadata for
cached store paths. Each line has format `Key: Value`. The fields relevant to
this task are:

| Field       | Description |
|-------------|-------------|
| `StorePath` | Full Nix store path, e.g. `/nix/store/<hash>-<name>` |
| `NarHash`   | Hash of the NAR-serialized content |
| `References`| Space-separated store path suffixes (without `/nix/store/` prefix) of runtime dependencies. May be empty. |
| `CA`        | Content Addressability descriptor. Determines how StorePath was computed. |

Other fields (`URL`, `Compression`, `FileHash`, `FileSize`, `NarSize`, `Sig`)
may be present but are not needed for store path verification.

## 2. Content Addressability (CA) Field

The `CA` field encodes the derivation type and the content hash used to compute
the store path. Supported formats:

### 2.1 Flat Fixed-Output Derivation
```
CA: fixed:sha256:<content_hash>
```
Single-file content, hash computed directly over the file bytes.

### 2.2 Recursive Fixed-Output Derivation
```
CA: fixed:r:sha256:<content_hash>
```
Directory tree or NAR-serialized content, hash computed over NAR serialization.

### 2.3 Text Hash Derivation
```
CA: text:sha256:<content_hash>
```
Builder scripts or text files created via `builtins.toFile`. References (if any)
are listed in the `References` field, not in the CA field.

## 3. Hash Encoding Formats

The `<content_hash>` in the CA field may use one of three encoding formats.
The auditor must detect the format automatically:

### 3.1 Hexadecimal (base-16)
- **Length**: 64 characters for SHA-256
- **Charset**: `[0-9a-f]`
- **Syntax in CA**: `sha256:<64-char-hex-string>`
- **Example**: `sha256:d9b56dd4fe1de178fce2f90dda0b46ce0c40e09da81a7938e49216caf7a4d02e`

### 3.2 Nix Base-32
- **Length**: 52 characters for SHA-256
- **Charset**: `0123456789abcdfghijklmnpqrsvwxyz` (digits 0-9 plus lowercase letters with **e, o, t, u omitted**)
- **Syntax in CA**: `sha256:<52-char-nix32-string>`
- **Example**: `sha256:0y8krs8s3i31nn147v9hlcxibnd9qjzca9df2h3i299pxmm1k551`

**Important**: This is NOT RFC 4648 base32. Nix uses a custom 32-character
alphabet. The encoding procedure extracts 5-bit groups from the raw hash bytes
in LSB-first order (see Section 5.5).

### 3.3 SRI (Subresource Integrity)
- **Syntax in CA**: `sha256-<standard-base64-with-padding>`
- **Charset for base64 portion**: `[A-Za-z0-9+/=]`
- **Length of base64 portion**: 44 characters for SHA-256
- **Example**: `sha256-2bVt1P4d4XjP4vkN2gtGzgxA4J2oGnk45JIWyveqQC4=`

**Note**: SRI uses a hyphen (`-`) between the algorithm name and the hash,
not a colon. This distinguishes it from hex and nix32 formats.

### 3.4 Format Detection Rules

Given a hash specification after the derivation type prefix:
1. If it matches `sha256-<value>`: **SRI format**. Decode `<value>` as standard base64.
2. If it matches `sha256:<value>`:
   - If `<value>` is 64 characters and all chars in `[0-9a-f]`: **hex format**
   - If `<value>` is 52 characters and all chars in `[0-9a-df-np-sv-z]`: **nix32 format**
   - Otherwise: **format error**
3. If no hash specification is recognized: **format error**

## 4. Store Path Computation Algorithms

All three derivation types share a common final pipeline:

```
fingerprint_string -> SHA-256 -> XOR-fold to 20 bytes -> Nix base-32 encode -> store path
```

The fingerprint string differs by derivation type.

### 4.1 Flat Fixed-Output Derivation

Flat mode uses a double-hash indirection:

```
Step 1: inner_hex = hex(SHA-256("fixed:out:sha256:<content_hash_hex>:"))
Step 2: fingerprint = "output:out:sha256:<inner_hex>:/nix/store:<name>"
```

**Critical detail**: The trailing colon in the inner hash input string
(`"fixed:out:sha256:<hash>:"`) is significant and must be included.

### 4.2 Recursive Fixed-Output Derivation

```
fingerprint = "source:sha256:<content_hash_hex>:/nix/store:<name>"
```

### 4.3 Text Hash Derivation

```
fingerprint = "text:<content_hash_hex>:<ref1>:<ref2>:...:/nix/store:<name>"
```

Where `<ref1>`, `<ref2>`, etc. are the **full store paths** (with `/nix/store/`
prefix) of the derivation's references, in **sorted lexicographic order**.

If the derivation has no references:
```
fingerprint = "text:<content_hash_hex>:/nix/store:<name>"
```

**Important**: References in narinfo files are listed as suffixes without the
`/nix/store/` prefix. The auditor must prepend `/nix/store/` to each reference
before including it in the fingerprint.

### 4.4 Common Pipeline

After constructing the fingerprint string:

```
digest = SHA-256(fingerprint.encode("utf-8"))    # 32 bytes
compressed = xor_fold(digest, 20)                 # 20 bytes
store_hash = nix_base32_encode(compressed)         # 32 characters
store_path = "/nix/store/" + store_hash + "-" + name
```

### 4.5 XOR Fold (Hash Compression)

Compress a 32-byte SHA-256 digest to 20 bytes:

```python
compressed = [0] * 20
for i, byte in enumerate(digest):
    compressed[i % 20] ^= byte
```

This preserves entropy better than simple truncation by XOR-folding the
remaining 12 bytes back over the first 20.

### 4.6 Nix Base-32 Encoding

Encode 20 bytes (160 bits) as 32 characters.

**Alphabet**: `0123456789abcdfghijklmnpqrsvwxyz` (32 chars; `e`, `o`, `t`, `u` omitted)

**Procedure** (produces output characters from left to right, i.e. most
significant group first):

```
For n from 31 down to 0:          # 32 groups, MSB-first output
    Extract 5-bit group at bit offset n*5 from the byte array:
        value = 0
        For bit from 0 to 4:
            source_bit = n * 5 + bit
            byte_index = source_bit // 8
            bit_index  = source_bit % 8          # LSB-first within each byte
            If the bit at (byte_index, bit_index) is set:
                value |= (1 << bit)
    Output alphabet[value]
```

Key points:
- Bit 0 of byte 0 is the **least significant bit** of the entire byte array
- Within each byte, bit indexing is **LSB-first** (bit 0 = least significant)
- Groups are emitted **most significant first** (n=31 first, n=0 last)

## 5. Output Schema

The auditor must write `/app/audit_report.json` conforming to this schema:

```json
{
  "audit_results": [
    {
      "filename": "<string: narinfo filename, e.g. 'abc123.narinfo'>",
      "status": "<string: one of 'valid', 'path_mismatch', 'hash_format_error', 'type_inconsistency', 'missing_field'>",
      "store_path": "<string: StorePath value from the narinfo file>",
      "computed_path": "<string|null: store path computed from CA, or null if hash undecodable/CA missing>",
      "content_hash_hex": "<string|null: content hash in hex encoding, or null>",
      "content_hash_nix32": "<string|null: content hash in nix32 encoding, or null>",
      "content_hash_sri": "<string|null: content hash in SRI encoding, or null>",
      "derivation_type": "<string|null: 'flat', 'recursive', or 'text' as claimed by CA, or null if CA missing>",
      "error_detail": "<string|null: human-readable error description, or null if valid>"
    }
  ],
  "summary": {
    "total": "<integer: total number of narinfo files processed>",
    "valid": "<integer: count of entries with status 'valid'>",
    "path_mismatch": "<integer>",
    "hash_format_error": "<integer>",
    "type_inconsistency": "<integer>",
    "missing_field": "<integer>"
  }
}
```

### 5.1 Field Semantics

- **filename**: The basename of the narinfo file (not a full path).
- **status**: Classification of the entry (see Section 6).
- **store_path**: The `StorePath` value verbatim from the narinfo file.
- **computed_path**: The store path recomputed from the CA content hash using
  the **claimed** derivation type. Set to `null` when the content hash cannot
  be decoded or CA is missing.
- **content_hash_hex**, **content_hash_nix32**, **content_hash_sri**: The
  content hash from the CA field converted to all three encoding formats. All
  three must be present when the hash is decodable; all `null` otherwise.
- **derivation_type**: The type as declared in the CA field (`flat`, `recursive`,
  or `text`). `null` if CA is missing.
- **error_detail**: A brief description of the detected issue. `null` for
  valid entries.

### 5.2 Ordering

The `audit_results` array must contain one entry per narinfo file. Entries
must be sorted by `filename` in lexicographic order.

## 6. Status Classification Rules

For each narinfo file, apply these rules in order:

1. **missing_field**: The CA field is absent from the narinfo file.

2. **hash_format_error**: The CA field is present but the content hash cannot
   be decoded — invalid hex characters, characters not in the Nix base-32
   alphabet, invalid base64 encoding, or unrecognized format.

3. **type_inconsistency**: The content hash is valid and decodes successfully,
   but the `computed_path` (using the claimed derivation type) does not match
   `store_path`. However, recomputing with a **different** derivation type
   produces a path that **does** match `store_path`. This indicates the CA
   field declares the wrong derivation type.

4. **path_mismatch**: The content hash is valid, `computed_path` does not
   match `store_path`, and no alternative derivation type produces a matching
   path either. The store path is simply inconsistent with the stated content hash.

5. **valid**: The `computed_path` matches `store_path` exactly.
