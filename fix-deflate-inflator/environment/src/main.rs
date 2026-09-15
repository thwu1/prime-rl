//! A standalone DEFLATE/zlib decompressor.
//!
//! Implements RFC 1951 (DEFLATE Compressed Data Format) with optional
//! RFC 1950 (zlib) wrapper support.
//!
//! Usage:
//!   zinflate [--raw] <input_file> [output_file]
//!   zinflate [--raw] < compressed > decompressed
//!
//! By default expects zlib-wrapped input. Use --raw for raw DEFLATE streams.


use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::process;

// ── Constants ────────────────────────────────────────────────────────────────

/// Adler-32 modulus constant.
const ADLER32_MOD: u32 = 65535;

/// Permutation order for code length alphabet in dynamic Huffman headers.
/// These indices specify the order in which 3-bit code lengths are transmitted
/// for the 19-symbol code length alphabet (RFC 1951 §3.2.7).
const CODE_LENGTH_ALPHABET_ORDER: [usize; 19] = [
    16, 17, 18, 8, 0, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

/// Base values for length codes 257..285 (RFC 1951 §3.2.5).
const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13,
    15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
    67, 83, 99, 115, 131, 163, 195, 227, 258,
];

/// Extra bits for length codes 257..285.
const LENGTH_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1,
    1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
    4, 4, 4, 4, 5, 5, 5, 5, 0,
];

/// Base values for distance codes 0..29 (RFC 1951 §3.2.5).
const DISTANCE_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25,
    33, 49, 65, 97, 129, 193, 257, 385, 513, 769,
    1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];

/// Extra bits for distance codes 0..29.
const DISTANCE_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3,
    4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
    9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
];

// ── Adler-32 Checksum ────────────────────────────────────────────────────────

/// Compute the Adler-32 checksum of a byte slice (RFC 1950 §9).
///
/// The checksum consists of two 16-bit sums:
///   s1 = 1 + sum of all bytes (mod ADLER32_MOD)
///   s2 = sum of all s1 values  (mod ADLER32_MOD)
///
/// Result: (s2 << 16) | s1
fn adler32_checksum(data: &[u8]) -> u32 {
    let mut s1: u32 = 1;
    let mut s2: u32 = 0;
    for chunk in data.chunks(5552) {
        for &byte in chunk {
            s1 += byte as u32;
            s2 += s1;
        }
        s1 %= ADLER32_MOD;
        s2 %= ADLER32_MOD;
    }
    (s2 << 16) | s1
}

// ── Bit-Level Reader ─────────────────────────────────────────────────────────

/// Reads bits from a byte slice in DEFLATE bit order.
///
/// DEFLATE packs data elements starting from the least-significant bit of each
/// byte. This reader maintains a 64-bit buffer to allow efficient multi-bit reads.
struct BitReader<'a> {
    data: &'a [u8],
    pos: usize,
    buf: u64,
    avail: u8,
}

impl<'a> BitReader<'a> {
    fn new(data: &'a [u8]) -> Self {
        BitReader {
            data,
            pos: 0,
            buf: 0,
            avail: 0,
        }
    }

    /// Pull bytes from input into the bit buffer until we have at least 56 bits
    /// (or the input is exhausted).
    #[inline]
    fn refill(&mut self) {
        while self.avail <= 56 && self.pos < self.data.len() {
            self.buf |= (self.data[self.pos] as u64) << self.avail;
            self.pos += 1;
            self.avail += 8;
        }
    }

    /// Read `n` bits (0 <= n <= 25) from the stream in standard LSB-first order.
    /// This is the correct ordering for all non-Huffman data elements in DEFLATE
    /// (block headers, extra bits for lengths, stored block sizes, etc.).
    #[inline]
    fn read_bits(&mut self, n: u8) -> u32 {
        debug_assert!(n <= 25);
        self.refill();
        let mask = (1u32 << n) - 1;
        let val = (self.buf as u32) & mask;
        self.buf >>= n;
        self.avail = self.avail.saturating_sub(n);
        val
    }

    /// Read extra bits for a distance code.
    ///
    /// Distance code extra bits encode the offset within the distance range.
    /// Like Huffman code bits, they are stored most-significant bit first in the
    /// stream per RFC 1951 §3.1.1. This function reads n bits and reverses their
    /// order to recover the MSB-first value.
    fn read_distance_extra(&mut self, n: u8) -> u32 {
        if n == 0 {
            return 0;
        }
        self.refill();
        let mask = (1u32 << n) - 1;
        let raw = (self.buf as u32) & mask;
        self.buf >>= n;
        self.avail = self.avail.saturating_sub(n);
        // Reverse bit order: the first bit read is the MSB of the extra value
        let mut reversed = 0u32;
        for i in 0..n {
            if raw & (1 << i) != 0 {
                reversed |= 1 << (n - 1 - i);
            }
        }
        reversed
    }

    /// Discard bits until the buffer is aligned to a byte boundary.
    /// Required before reading stored block headers.
    fn align_to_byte(&mut self) {
        let discard = self.avail & 7;
        if discard > 0 {
            self.buf >>= discard;
            self.avail -= discard;
        }
    }

    /// Read a single byte (after ensuring byte-alignment internally via read_bits).
    fn read_u8(&mut self) -> u8 {
        self.read_bits(8) as u8
    }

    /// Read a 16-bit little-endian value.
    fn read_u16_le(&mut self) -> u16 {
        let lo = self.read_bits(8) as u16;
        let hi = self.read_bits(8) as u16;
        (hi << 8) | lo
    }
}

// ── Canonical Huffman Tree ───────────────────────────────────────────────────

/// A canonical Huffman code table for decoding.
///
/// Constructed from an array of per-symbol code lengths using the algorithm
/// in RFC 1951 §3.2.2. Decoding walks the table one bit at a time, comparing
/// the accumulated code value against the range of codes at each length.
struct HuffmanTree {
    /// How many codes exist at each bit length (index 0 unused; indices 1..15).
    counts: [u16; 16],
    /// Symbols sorted first by ascending code length, then by symbol value.
    symbols: Vec<u16>,
    /// The longest code in this tree (0 if the tree is empty).
    max_len: u8,
}

impl HuffmanTree {
    /// Build a Huffman tree from per-symbol code lengths.
    ///
    /// `lengths[i]` is the code length for symbol `i`. A length of 0 means
    /// the symbol does not appear in the code.
    fn from_lengths(lengths: &[u8]) -> Result<Self, String> {
        // Step 1 – count codes of each length
        let mut counts = [0u16; 16];
        for &len in lengths {
            if len > 15 {
                return Err(format!("Code length {} exceeds maximum of 15", len));
            }
            if len > 0 {
                counts[len as usize] += 1;
            }
        }

        let max_len = (1u8..16)
            .rev()
            .find(|&i| counts[i as usize] > 0)
            .unwrap_or(0);

        // Compute offsets into the sorted symbol array
        let mut offsets = [0u16; 16];
        let mut total = 0u16;
        for i in 1..16usize {
            offsets[i] = total;
            total += counts[i];
        }

        // Fill in the symbol array in order
        let mut symbols = vec![0u16; total as usize];
        for (sym, &len) in lengths.iter().enumerate() {
            if len > 0 {
                let off = offsets[len as usize] as usize;
                symbols[off] = sym as u16;
                offsets[len as usize] += 1;
            }
        }

        Ok(HuffmanTree {
            counts,
            symbols,
            max_len,
        })
    }

    /// Decode one symbol from the bit stream using the canonical Huffman table.
    fn decode(&self, reader: &mut BitReader) -> Result<u16, String> {
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
    }
}

// ── Fixed Huffman Trees (RFC 1951 §3.2.6) ────────────────────────────────────

/// Build the fixed literal/length Huffman tree.
///
///   Lit Value   Bits   Codes
///   ---------   ----   -----
///   0 – 143      8    00110000 .. 10111111
///   144 – 255    9    110010000 .. 111111111
///   256 – 279    7    0000000 .. 0010111
///   280 – 287    8    11000000 .. 11000111
fn fixed_litlen_tree() -> HuffmanTree {
    let mut lengths = vec![0u8; 288];
    for i in 0..=143 {
        lengths[i] = 8;
    }
    for i in 144..=255 {
        lengths[i] = 9;
    }
    for i in 256..=279 {
        lengths[i] = 7;
    }
    for i in 280..=287 {
        lengths[i] = 8;
    }
    HuffmanTree::from_lengths(&lengths).expect("fixed litlen tree must be valid")
}

/// Build the fixed distance Huffman tree (all 32 symbols use 5-bit codes).
fn fixed_dist_tree() -> HuffmanTree {
    let lengths = vec![5u8; 32];
    HuffmanTree::from_lengths(&lengths).expect("fixed dist tree must be valid")
}

// ── Dynamic Huffman Trees (RFC 1951 §3.2.7) ─────────────────────────────────

/// Parse the dynamic Huffman tree definitions from the bit stream.
///
/// A dynamic Huffman block header encodes three trees in sequence:
///   1. A "code length" Huffman tree (up to 19 symbols)
///   2. Using that tree, decode the literal/length tree (up to 286 symbols)
///   3. Using that tree, decode the distance tree (up to 30 symbols)
fn read_dynamic_trees(reader: &mut BitReader) -> Result<(HuffmanTree, HuffmanTree), String> {
    let hlit = reader.read_bits(5) as usize + 257;
    let hdist = reader.read_bits(5) as usize + 1;
    let hclen = reader.read_bits(4) as usize + 4;

    if hlit > 286 {
        return Err(format!("HLIT value {} exceeds maximum 286", hlit));
    }
    if hdist > 30 {
        return Err(format!("HDIST value {} exceeds maximum 30", hdist));
    }

    // Read the code length alphabet code lengths (3 bits each) in the
    // permuted order specified by CODE_LENGTH_ALPHABET_ORDER.
    let mut cl_lengths = [0u8; 19];
    for i in 0..hclen {
        cl_lengths[CODE_LENGTH_ALPHABET_ORDER[i]] = reader.read_bits(3) as u8;
    }

    let cl_tree = HuffmanTree::from_lengths(&cl_lengths)?;

    // Decode the concatenated litlen + distance code lengths
    let total_codes = hlit + hdist;
    let mut lengths = vec![0u8; total_codes];
    let mut i = 0;

    while i < total_codes {
        let sym = cl_tree.decode(reader)?;
        match sym {
            0..=15 => {
                // Literal code length value
                lengths[i] = sym as u8;
                i += 1;
            }
            16 | 17 | 18 => {
                // TODO: Implement run-length encoded code lengths.
                //
                // These symbols encode repeated code length values to
                // compress the tree description. Each reads a different
                // number of extra bits to determine the run parameters.
                return Err(format!(
                    "Code length RLE symbol {} not yet handled",
                    sym
                ));
            }
            _ => {
                return Err(format!("Invalid code length symbol {}", sym));
            }
        }
    }

    let litlen_tree = HuffmanTree::from_lengths(&lengths[..hlit])?;
    let dist_tree = HuffmanTree::from_lengths(&lengths[hlit..])?;

    Ok((litlen_tree, dist_tree))
}

// ── Block Decompression ──────────────────────────────────────────────────────

/// Decompress a single Huffman-coded DEFLATE block (BTYPE = 01 or 10).
///
/// Reads literal/length symbols from `litlen_tree` and distance symbols from
/// `dist_tree`, appending decompressed bytes to `output`.
fn decode_huffman_block(
    reader: &mut BitReader,
    litlen_tree: &HuffmanTree,
    dist_tree: &HuffmanTree,
    output: &mut Vec<u8>,
) -> Result<(), String> {
    loop {
        let symbol = litlen_tree.decode(reader)?;

        match symbol {
            // Literal byte (0..255)
            0..=255 => {
                output.push(symbol as u8);
            }

            // End-of-block marker (256)
            256 => {
                return Ok(());
            }

            // Length/distance pair (257..285)
            257..=285 => {
                // TODO: Implement LZ77 length/distance back-reference decoding.
                //
                // Use LENGTH_BASE and LENGTH_EXTRA tables to determine the
                // match length from the symbol. Then decode a distance symbol
                // from dist_tree and use DISTANCE_BASE and DISTANCE_EXTRA to
                // determine the backward distance. Finally, copy `length`
                // bytes from the output buffer at position
                // (output.len() - distance).
                return Err("LZ77 back-reference decoding not yet implemented".into());
            }

            _ => {
                return Err(format!("Invalid litlen symbol {}", symbol));
            }
        }
    }
}

// ── Top-Level Inflate ────────────────────────────────────────────────────────

/// Decompress a DEFLATE stream, optionally wrapped in a zlib container.
fn inflate(input: &[u8], zlib_wrapped: bool) -> Result<Vec<u8>, String> {
    let mut reader = BitReader::new(input);
    let mut output = Vec::new();

    // ── Parse zlib header (RFC 1950 §2.2) ──
    if zlib_wrapped {
        let cmf = reader.read_u8();
        let flg = reader.read_u8();

        // CM must be 8 (deflate)
        if cmf & 0x0F != 8 {
            return Err(format!(
                "Unsupported compression method {} (expected 8)",
                cmf & 0x0F
            ));
        }

        // CINFO must be ≤ 7 (window size 2^(CINFO+8) ≤ 32768)
        if (cmf >> 4) > 7 {
            return Err("CINFO exceeds maximum window size".into());
        }

        // Header checksum: (CMF*256 + FLG) must be divisible by 31
        if ((cmf as u16) * 256 + flg as u16) % 31 != 0 {
            return Err("Zlib header checksum (FCHECK) failed".into());
        }

        // FDICT (preset dictionary) not supported
        if flg & 0x20 != 0 {
            return Err("Preset dictionary (FDICT) not supported".into());
        }
    }

    // ── Process DEFLATE blocks ──
    loop {
        let bfinal = reader.read_bits(1);
        let btype = reader.read_bits(2);

        match btype {
            0b00 => {
                // Stored (no compression)
                reader.align_to_byte();
                let len = reader.read_u16_le();
                let nlen = reader.read_u16_le();
                if len != !nlen {
                    return Err(format!(
                        "Stored block LEN/NLEN mismatch: 0x{:04X} vs 0x{:04X}",
                        len, nlen
                    ));
                }
                for _ in 0..len {
                    output.push(reader.read_u8());
                }
            }

            0b01 => {
                // Compressed with fixed Huffman codes
                let litlen = fixed_litlen_tree();
                let dist = fixed_dist_tree();
                decode_huffman_block(&mut reader, &litlen, &dist, &mut output)?;
            }

            0b10 => {
                // Compressed with dynamic Huffman codes
                let (litlen, dist) = read_dynamic_trees(&mut reader)?;
                decode_huffman_block(&mut reader, &litlen, &dist, &mut output)?;
            }

            0b11 => {
                return Err("Reserved block type (0b11) encountered".into());
            }

            _ => unreachable!(),
        }

        if bfinal != 0 {
            break;
        }
    }

    // ── Verify zlib trailer (Adler-32, big-endian) ──
    if zlib_wrapped {
        reader.align_to_byte();
        let b3 = reader.read_u8() as u32;
        let b2 = reader.read_u8() as u32;
        let b1 = reader.read_u8() as u32;
        let b0 = reader.read_u8() as u32;
        let expected = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0;
        let actual = adler32_checksum(&output);

        if expected != actual {
            return Err(format!(
                "Adler-32 checksum mismatch: expected 0x{:08X}, computed 0x{:08X}",
                expected, actual
            ));
        }
    }

    Ok(output)
}

// ── CLI ──────────────────────────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = env::args().collect();

    let mut raw_mode = false;
    let mut input_file: Option<String> = None;
    let mut output_file: Option<String> = None;

    let mut idx = 1;
    while idx < args.len() {
        match args[idx].as_str() {
            "--raw" => raw_mode = true,
            "--help" | "-h" => {
                eprintln!("Usage: {} [--raw] [<input> [<output>]]", args[0]);
                eprintln!();
                eprintln!("Decompress a zlib (RFC 1950) or raw DEFLATE (RFC 1951) stream.");
                eprintln!();
                eprintln!("Options:");
                eprintln!("  --raw    Expect raw DEFLATE input (no zlib header/trailer)");
                eprintln!();
                eprintln!("If no files are given, reads from stdin and writes to stdout.");
                process::exit(0);
            }
            other => {
                if input_file.is_none() {
                    input_file = Some(other.to_string());
                } else if output_file.is_none() {
                    output_file = Some(other.to_string());
                } else {
                    eprintln!("Error: unexpected argument '{}'", other);
                    process::exit(1);
                }
            }
        }
        idx += 1;
    }

    // Read input
    let input_data = match &input_file {
        Some(path) => fs::read(path).unwrap_or_else(|e| {
            eprintln!("Error: cannot read '{}': {}", path, e);
            process::exit(1);
        }),
        None => {
            let mut buf = Vec::new();
            io::stdin().read_to_end(&mut buf).unwrap_or_else(|e| {
                eprintln!("Error: cannot read stdin: {}", e);
                process::exit(1);
            });
            buf
        }
    };

    // Decompress
    match inflate(&input_data, !raw_mode) {
        Ok(decompressed) => match &output_file {
            Some(path) => {
                fs::write(path, &decompressed).unwrap_or_else(|e| {
                    eprintln!("Error: cannot write '{}': {}", path, e);
                    process::exit(1);
                });
            }
            None => {
                io::stdout().write_all(&decompressed).unwrap_or_else(|e| {
                    eprintln!("Error: cannot write to stdout: {}", e);
                    process::exit(1);
                });
            }
        },
        Err(msg) => {
            eprintln!("Decompression failed: {}", msg);
            process::exit(1);
        }
    }
}
