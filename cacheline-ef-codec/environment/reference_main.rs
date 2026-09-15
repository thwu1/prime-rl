//! CachelineEf: cache-line-compressed storage for sorted integer sequences.
//!
//! Each block of CHUNK values is packed into a 64-byte cache-line-aligned struct,
//! enabling single-cache-line random-access lookups.
//!

use std::env;
use std::io::{self, BufRead};

const CHUNK: usize = 44;

/// A single 64-byte block storing up to CHUNK sorted values.
///
/// Layout:  [offset: 4B][high: 16B][low: 44B] = 64 bytes.
///
/// The `high` field is a 128-bit bitvector stored as raw little-endian bytes.
/// It encodes the relative high parts of each value using a unary scheme that
/// maps each value index to a distinct set bit position.
#[repr(C, align(64))]
#[derive(Clone, Copy)]
struct CachelineEf {
    offset: u32,
    high: [u8; 16],
    low: [u8; CHUNK],
}

impl Default for CachelineEf {
    fn default() -> Self {
        Self {
            offset: 0,
            high: [0u8; 16],
            low: [0u8; CHUNK],
        }
    }
}

struct CachelineEfVec {
    blocks: Vec<CachelineEf>,
    len: usize,
}

impl CachelineEfVec {
    fn try_new(vals: &[u64]) -> Option<Self> {
        if vals.is_empty() {
            return Some(Self {
                blocks: Vec::new(),
                len: 0,
            });
        }
        for w in vals.windows(2) {
            if w[1] < w[0] {
                return None;
            }
        }

        let n_blocks = vals.len().div_ceil(CHUNK);
        let mut blocks = vec![CachelineEf::default(); n_blocks];

        for (b, chunk) in vals.chunks(CHUNK).enumerate() {
            let base = (chunk[0] >> 8) as u32;
            blocks[b].offset = base;

            for (i, &v) in chunk.iter().enumerate() {
                let rel = (v >> 8) as u32 - base;
                let pos = rel + i as u32;
                if pos >= 128 {
                    return None;
                }
                // Set bit `pos` in the 128-bit bitvector (little-endian byte order)
                blocks[b].high[pos as usize / 8] |= 1u8 << (pos % 8);
                blocks[b].low[i] = v as u8;
            }
        }

        Some(Self {
            blocks,
            len: vals.len(),
        })
    }

    fn index(&self, idx: usize) -> u64 {
        let blk = &self.blocks[idx / CHUNK];
        let local = idx % CHUNK;

        let bit_pos = sel128(&blk.high, local as u32);
        let rel = bit_pos - local as u32;

        ((blk.offset + rel) as u64) << 8 | blk.low[local] as u64
    }

    fn num_blocks(&self) -> usize {
        self.blocks.len()
    }
    fn size_bytes(&self) -> usize {
        self.blocks.len() * 64
    }
}

/// Load the two 64-bit words from a 16-byte little-endian bitvector.
fn load_words(high: &[u8; 16]) -> (u64, u64) {
    let lo = u64::from_le_bytes(high[0..8].try_into().unwrap());
    let hi = u64::from_le_bytes(high[8..16].try_into().unwrap());
    (lo, hi)
}

/// Position of the r-th set bit (0-indexed) in a 64-bit word.
/// Clears the lowest set bit r times, then returns trailing zeros.
fn sel64(mut w: u64, r: u32) -> u32 {
    for _ in 0..r {
        w &= w.wrapping_sub(1);
    }
    w.trailing_zeros()
}

/// Position of the r-th set bit in a 128-bit bitvector (16 LE bytes).
/// Uses popcount on the lower word to decide which half contains the target.
fn sel128(high: &[u8; 16], r: u32) -> u32 {
    let (lo, hi) = load_words(high);
    let lo_pop = lo.count_ones();
    if r < lo_pop {
        sel64(lo, r)
    } else {
        64 + sel64(hi, r - lo_pop)
    }
}

fn read_values() -> Vec<u64> {
    let stdin = io::stdin();
    stdin
        .lock()
        .lines()
        .filter_map(|l| l.ok())
        .filter_map(|l| l.trim().parse().ok())
        .collect()
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mode = args.get(1).map(|s| s.as_str()).unwrap_or("demo");

    match mode {
        "roundtrip" => {
            let vals = read_values();
            if vals.is_empty() {
                return;
            }
            let ef = CachelineEfVec::try_new(&vals).expect("construction failed");
            for i in 0..vals.len() {
                println!("{}", ef.index(i));
            }
        }
        "info" => {
            let vals = read_values();
            let ef = CachelineEfVec::try_new(&vals).expect("construction failed");
            let sb = ef.size_bytes();
            println!("num_values={}", vals.len());
            println!("num_blocks={}", ef.num_blocks());
            println!("size_bytes={}", sb);
            if vals.is_empty() {
                println!("bits_per_value=0.00");
            } else {
                println!("bits_per_value={:.2}", sb as f64 * 8.0 / vals.len() as f64);
            }
        }
        _ => {
            // Demo: encode/decode a sample sequence
            let vals: Vec<u64> = (0..100).map(|i| i * 50).collect();
            let ef = CachelineEfVec::try_new(&vals).expect("construction failed");
            println!(
                "Encoded {} values into {} blocks ({} bytes)",
                vals.len(),
                ef.num_blocks(),
                ef.size_bytes()
            );
            let mut bad = 0usize;
            for (i, &expected) in vals.iter().enumerate() {
                let got = ef.index(i);
                if got != expected {
                    eprintln!("MISMATCH at {i}: expected {expected}, got {got}");
                    bad += 1;
                }
            }
            if bad == 0 {
                println!("All {} values decoded correctly.", vals.len());
            } else {
                eprintln!("{bad} mismatches!");
                std::process::exit(1);
            }
        }
    }
}
