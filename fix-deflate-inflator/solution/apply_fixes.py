#!/usr/bin/env python3
"""
Apply all fixes to the zinflate decompressor:
1. Fix Adler-32 modulus (65535 -> 65521)
2. Fix CODE_LENGTH_ALPHABET_ORDER (swap positions 3 and 4)
3. Implement HuffmanTree::decode() - canonical Huffman decoding
4. Implement RLE code length symbols (16, 17, 18)
5. Implement LZ77 back-reference decoding (using read_bits, NOT read_distance_extra)
"""


import sys

def main():
    path = sys.argv[1]
    with open(path, 'r') as f:
        code = f.read()

    # Fix 1: Adler-32 modulus must be 65521 (largest prime < 2^16)
    code = code.replace(
        'const ADLER32_MOD: u32 = 65535;',
        'const ADLER32_MOD: u32 = 65521;'
    )
    print("Fixed Adler-32 modulus")

    # Fix 2: CODE_LENGTH_ALPHABET_ORDER positions 3,4 are swapped
    code = code.replace(
        '16, 17, 18, 8, 0, 7, 9,',
        '16, 17, 18, 0, 8, 7, 9,'
    )
    print("Fixed CODE_LENGTH_ALPHABET_ORDER")

    # Fix 3: Implement canonical Huffman decode
    old_decode = """    fn decode(&self, reader: &mut BitReader) -> Result<u16, String> {
        // TODO: Implement canonical Huffman decoding.
        //
        // The counts array tells how many codes exist at each bit length.
        // The symbols array contains all symbols sorted by ascending code
        // length, then by symbol value within the same length.
        //
        // Huffman codes in DEFLATE are read MSB-first from the bit stream
        // (one bit at a time), even though all other data elements are
        // read LSB-first.
        Err("Huffman decoding not yet implemented".into())
    }"""

    new_decode = """    fn decode(&self, reader: &mut BitReader) -> Result<u16, String> {
        let mut code: u32 = 0;
        let mut first: u32 = 0;
        let mut index: usize = 0;

        for len in 1..=self.max_len {
            code |= reader.read_bits(1);
            let count = self.counts[len as usize] as u32;
            if code < first + count {
                let sym_idx = index + (code - first) as usize;
                if sym_idx >= self.symbols.len() {
                    return Err("Huffman symbol index out of bounds".into());
                }
                return Ok(self.symbols[sym_idx]);
            }
            index += count as usize;
            first = (first + count) << 1;
            code <<= 1;
        }

        Err("Invalid Huffman code (no matching symbol found)".into())
    }"""

    assert old_decode in code, "Could not find Huffman decode stub"
    code = code.replace(old_decode, new_decode)
    print("Implemented Huffman decode")

    # Fix 4: Implement RLE code length symbols 16, 17, 18
    old_rle = """            16 | 17 | 18 => {
                // TODO: Implement run-length encoded code lengths.
                //
                // These symbols encode repeated code length values to
                // compress the tree description. Each reads a different
                // number of extra bits to determine the run parameters.
                return Err(format!(
                    "Code length RLE symbol {} not yet handled",
                    sym
                ));
            }"""

    new_rle = """            16 => {
                if i == 0 {
                    return Err("Code 16 (repeat previous) at start of lengths".into());
                }
                let repeat = reader.read_bits(2) as usize + 3;
                let prev = lengths[i - 1];
                for _ in 0..repeat {
                    if i >= total_codes {
                        return Err("Code length repeat overflow".into());
                    }
                    lengths[i] = prev;
                    i += 1;
                }
            }
            17 => {
                let repeat = reader.read_bits(3) as usize + 3;
                for _ in 0..repeat {
                    if i >= total_codes {
                        return Err("Code length repeat overflow".into());
                    }
                    lengths[i] = 0;
                    i += 1;
                }
            }
            18 => {
                let repeat = reader.read_bits(7) as usize + 11;
                for _ in 0..repeat {
                    if i >= total_codes {
                        return Err("Code length repeat overflow".into());
                    }
                    lengths[i] = 0;
                    i += 1;
                }
            }"""

    assert old_rle in code, "Could not find RLE stub"
    code = code.replace(old_rle, new_rle)
    print("Implemented RLE code length symbols")

    # Fix 5: Implement LZ77 back-reference decoding
    # IMPORTANT: uses read_bits for distance extra (NOT the buggy read_distance_extra)
    old_lz77 = """            257..=285 => {
                // TODO: Implement LZ77 length/distance back-reference decoding.
                //
                // Use LENGTH_BASE and LENGTH_EXTRA tables to determine the
                // match length from the symbol. Then decode a distance symbol
                // from dist_tree and use DISTANCE_BASE and DISTANCE_EXTRA to
                // determine the backward distance. Finally, copy `length`
                // bytes from the output buffer at position
                // (output.len() - distance).
                return Err("LZ77 back-reference decoding not yet implemented".into());
            }"""

    new_lz77 = """            257..=285 => {
                let len_idx = (symbol - 257) as usize;
                let length = LENGTH_BASE[len_idx] as usize
                    + reader.read_bits(LENGTH_EXTRA[len_idx]) as usize;

                let dist_code = dist_tree.decode(reader)? as usize;
                if dist_code >= DISTANCE_BASE.len() {
                    return Err(format!("Distance code {} out of range", dist_code));
                }

                let distance = DISTANCE_BASE[dist_code] as usize
                    + reader.read_bits(DISTANCE_EXTRA[dist_code]) as usize;

                if distance == 0 || distance > output.len() {
                    return Err(format!(
                        "Invalid back-reference: distance={}, available={}",
                        distance,
                        output.len()
                    ));
                }

                for _ in 0..length {
                    let byte = output[output.len() - distance];
                    output.push(byte);
                }
            }"""

    assert old_lz77 in code, "Could not find LZ77 stub"
    code = code.replace(old_lz77, new_lz77)
    print("Implemented LZ77 back-reference decoding")

    with open(path, 'w') as f:
        f.write(code)

    print("All fixes applied successfully")

if __name__ == '__main__':
    main()
