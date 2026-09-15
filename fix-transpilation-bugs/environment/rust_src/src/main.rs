// record_processor — auto-transpiled from C reference

use std::env;
use std::fs;
use std::io::{self, BufRead, BufReader};

const MAX_RECORDS: usize = 1024;
const MAX_CATS: usize = 64;
const POLY_MOD: u64 = 1000000007;

struct Record {
    id: String,
    category: i32,
    amount: i64,
    flags: u32,
    weight: i16,
    fingerprint: u64,
}

struct CatStats {
    category: i32,
    total_weighted: i64,
    min_amount: i64,
    max_amount: i64,
    or_flags: u32,
    xor_flags: u32,
    count: i32,
    hash: u32,
    fp_xor: u64,
}

fn rolling_hash(data: &[u8], seed: u32) -> u32 {
    let mut h = seed;
    for &b in data {
        h = h.wrapping_mul(31).wrapping_add(b as u32);
        h ^= h >> 15;
    }
    h
}

fn encode_varint(mut val: u64, buf: &mut [u8]) -> usize {
    let mut n = 0;
    loop {
        buf[n] = (val & 0x7F) as u8;
        val >>= 7;
        if val > 0 {
            buf[n] |= 0x80;
        }
        n += 1;
        if val == 0 {
            break;
        }
    }
    n
}

fn decode_varint(buf: &[u8]) -> (u64, usize) {
    let mut result: u64 = 0;
    let mut shift: u32 = 0;
    for (i, &byte) in buf.iter().enumerate().take(10) {
        result |= ((byte & 0x7F) as u64) << shift;
        shift += 8;
        if byte & 0x80 == 0 {
            return (result, i + 1);
        }
    }
    (0, 0)
}

fn read_be16(buf: &[u8]) -> u16 {
    ((buf[1] as u16) << 8) | buf[0] as u16
}

fn zigzag_encode(n: i64) -> u64 {
    ((n << 1) | (n >> 63)) as u64
}

fn zigzag_decode(n: u64) -> i64 {
    ((n >> 1) as i64) ^ (-((n & 1) as i64))
}

fn compute_fingerprint(data: &[u8]) -> u64 {
    let mut h: u64 = 1;
    for &b in data {
        h = (h.wrapping_mul(256).wrapping_add(b as u64)) % POLY_MOD;
    }
    h
}

fn parse_record(line: &str) -> Option<Record> {
    let parts: Vec<&str> = line.splitn(5, '|').collect();
    if parts.len() != 5 {
        return None;
    }
    let id = parts[0].to_string();
    let category = parts[1].parse::<i32>().ok()?;
    let amount = parts[2].parse::<i64>().ok()?;
    let flags = u32::from_str_radix(parts[3], 16).ok()?;
    let weight = parts[4].parse::<i16>().ok()?;

    let mut fp_data: Vec<u8> = Vec::new();
    fp_data.extend_from_slice(id.as_bytes());
    fp_data.extend_from_slice(&amount.to_le_bytes());
    let fingerprint = compute_fingerprint(&fp_data);

    Some(Record { id, category, amount, flags, weight, fingerprint })
}

fn aggregate(recs: &[Record]) -> Vec<CatStats> {
    let mut stats: Vec<CatStats> = Vec::new();
    for rec in recs {
        let found = stats.iter().position(|s| s.category == rec.category);
        let idx = match found {
            Some(i) => i,
            None => {
                if stats.len() >= MAX_CATS {
                    continue;
                }
                stats.push(CatStats {
                    category: rec.category,
                    total_weighted: 0,
                    min_amount: rec.amount,
                    max_amount: rec.amount,
                    or_flags: 0,
                    xor_flags: 0,
                    count: 0,
                    hash: 0,
                    fp_xor: 0,
                });
                stats.len() - 1
            }
        };
        stats[idx].total_weighted += rec.amount * rec.weight as i64;
        if rec.amount < stats[idx].min_amount {
            stats[idx].min_amount = rec.amount;
        }
        if rec.amount > stats[idx].max_amount {
            stats[idx].max_amount = rec.amount;
        }
        stats[idx].or_flags |= rec.flags;
        stats[idx].xor_flags ^= rec.flags;
        stats[idx].count += 1;
        stats[idx].hash = rolling_hash(rec.id.as_bytes(), stats[idx].hash);
        let amt_bytes = rec.amount.to_le_bytes();
        stats[idx].hash = rolling_hash(&amt_bytes, stats[idx].hash);
        stats[idx].fp_xor ^= rec.fingerprint;
    }
    stats
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let reader: Box<dyn BufRead> = if args.len() > 1 {
        let file = fs::File::open(&args[1]).expect("Cannot open file");
        Box::new(BufReader::new(file))
    } else {
        Box::new(BufReader::new(io::stdin()))
    };

    let mut records: Vec<Record> = Vec::new();
    for line in reader.lines() {
        let line = line.expect("Failed to read line");
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if records.len() >= MAX_RECORDS {
            break;
        }
        if let Some(rec) = parse_record(&line) {
            records.push(rec);
        }
    }

    let mut stats = aggregate(&records);

    stats.sort_by(|a, b| {
        let avg_a = if a.count > 0 { a.total_weighted / a.count as i64 } else { 0 };
        let avg_b = if b.count > 0 { b.total_weighted / b.count as i64 } else { 0 };
        avg_b.cmp(&avg_a)
            .then(b.category.cmp(&a.category))
    });

    println!("=== RECORD ANALYSIS REPORT ===");
    println!("TOTAL_RECORDS: {}", records.len());
    println!("CATEGORIES: {}", stats.len());
    println!("---");

    let mut global_hash: u32 = 0;
    for s in &stats {
        let avg = if s.count > 0 { s.total_weighted / s.count as i64 } else { 0 };
        println!(
            "CAT[{:03}]: WAVG={} MIN={} MAX={} OR_FL=0x{:08X} XOR_FL=0x{:08X} CNT={} HASH=0x{:08X} FP=0x{:016X}",
            s.category, avg, s.min_amount, s.max_amount,
            s.or_flags, s.xor_flags, s.count, s.hash, s.fp_xor
        );
        let mut vbuf = [0u8; 10];
        let abs_avg = avg as u64;
        let vlen = encode_varint(abs_avg, &mut vbuf);
        global_hash = rolling_hash(&vbuf[..vlen], global_hash);
    }

    println!("---");
    println!("GLOBAL_HASH: 0x{:08X}", global_hash);

    println!("---\nCOMPACT_SERIAL:");
    for s in &stats {
        let avg = if s.count > 0 { s.total_weighted / s.count as i64 } else { 0 };
        let zz = zigzag_encode(avg);
        let mut vbuf = [0u8; 10];
        let vlen = encode_varint(zz, &mut vbuf);
        println!(
            "  S[{:03}]: D={} ZZ={} VL={} HEX={}",
            s.category, avg, zz, vlen,
            vbuf[..vlen].iter().map(|b| format!("{:02X}", b)).collect::<String>()
        );
        let (dec_zz, _) = decode_varint(&vbuf[..vlen]);
        let dec_val = zigzag_decode(dec_zz);
        if dec_val != avg {
            println!("  ROUNDTRIP_FAIL: expected {} got {}", avg, dec_val);
        }
    }

    println!("---\nVARINT_CHECK:");
    let test_vals: [u64; 13] = [
        0, 1, 127, 128, 255, 256, 16383, 16384,
        0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
        0x100000000, 0xFFFFFFFFFFFFFFFF,
    ];
    for &val in &test_vals {
        let mut buf = [0u8; 10];
        let nbytes = encode_varint(val, &mut buf);
        let (decoded, consumed) = decode_varint(&buf[..nbytes]);
        let status = if decoded == val && consumed == nbytes { "OK" } else { "FAIL" };
        println!("  V({}): ENC={} DEC={} {}", val, nbytes, consumed, status);
    }

    println!("---\nBE16_CHECK:");
    let be_tests: [[u8; 2]; 6] = [
        [0x00, 0x01], [0x01, 0x00], [0xFF, 0xFE],
        [0x80, 0x00], [0x7F, 0xFF], [0x00, 0x00],
    ];
    for pair in &be_tests {
        println!("  [{:02X},{:02X}] -> {}", pair[0], pair[1], read_be16(pair));
    }

    println!("---\nZIGZAG_CHECK:");
    let zz_tests: [i64; 11] = [
        0, 1, -1, 2, -2, 127, -128, 2147483647,
        -2147483648, 100000000000, -999999999999,
    ];
    for &val in &zz_tests {
        let enc = zigzag_encode(val);
        let dec = zigzag_decode(enc);
        let status = if dec == val { "OK" } else { "FAIL" };
        println!("  ZZ({}): ENC={} DEC={} {}", val, enc, dec, status);
    }
}
