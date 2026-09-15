// qc_ref.rs — Standalone reference implementation of quickcheck shrinking.
// Compile: rustc /app/qc-ref/qc_ref.rs -o /app/qc-ref/qc-ref
// Usage:   /app/qc-ref/qc-ref <command> <value>

use std::env;

fn shrink_nonneg(x: i64) -> Vec<i64> {
    if x == 0 {
        return vec![];
    }
    let mut result = vec![0i64];
    let mut i = x / 2;
    while i > 0 {
        result.push(x - i);
        i /= 2;
    }
    result
}

fn shrink_int(x: i64) -> Vec<i64> {
    if x == 0 {
        return vec![];
    }
    let i_init = x / 2; // Rust integer division truncates toward zero
    let mut result = vec![0i64];
    if i_init < 0 {
        result.push(x.abs());
    }
    let mut i = i_init;
    while i != 0 {
        result.push(x - i);
        i /= 2;
    }
    result
}

fn shrink_vec(xs: &[i64], use_nonneg: bool) -> Vec<Vec<i64>> {
    if xs.is_empty() {
        return vec![];
    }

    let elem_shrinker = if use_nonneg { shrink_nonneg } else { shrink_int };
    let n = xs.len();
    let mut results: Vec<Vec<i64>> = vec![];

    // Phase 0: yield empty vec
    results.push(vec![]);

    // Phase 1: chunk removal (mirrors VecShrinker)
    let mut size = n / 2;
    let mut offset = size;
    while size > 0 {
        let mut v = Vec::new();
        v.extend_from_slice(&xs[..offset - size]);
        v.extend_from_slice(&xs[std::cmp::min(offset, n)..]);
        results.push(v);
        offset += size;
        if offset > n {
            size /= 2;
            offset = size;
        }
    }

    // Phase 2: element shrinking
    // offset is 0 after phase 1 ends; set to 1 (mirrors VecShrinker guard)
    let mut pos: usize = 1;
    let mut cur_shrinks = elem_shrinker(xs[0]);
    let mut si = 0usize;

    loop {
        if si < cur_shrinks.len() {
            let e = cur_shrinks[si];
            si += 1;
            let mut v = Vec::new();
            v.extend_from_slice(&xs[..pos - 1]);
            v.push(e);
            v.extend_from_slice(&xs[pos..]);
            results.push(v);
        } else {
            if pos >= n {
                break;
            }
            cur_shrinks = elem_shrinker(xs[pos]);
            si = 0;
            pos += 1;
        }
    }

    results
}

fn format_i64_vec(v: &[i64]) -> String {
    let items: Vec<String> = v.iter().map(|x| x.to_string()).collect();
    format!("[{}]", items.join(", "))
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: {} <command> <value>", args[0]);
        eprintln!();
        eprintln!("Commands:");
        eprintln!("  shrink-nonneg <n>              Shrink non-negative integer");
        eprintln!("  shrink-int <n>                 Shrink signed integer");
        eprintln!("  shrink-bool <true|false>       Shrink boolean");
        eprintln!("  shrink-vec <a,b,c,...>         Shrink vec (nonneg element shrinker)");
        eprintln!("  shrink-vec-int <a,b,c,...>     Shrink vec (signed int element shrinker)");
        std::process::exit(1);
    }

    match args[1].as_str() {
        "shrink-nonneg" => {
            let x: i64 = args[2].parse().expect("Invalid integer");
            println!("{}", format_i64_vec(&shrink_nonneg(x)));
        }
        "shrink-int" => {
            let x: i64 = args[2].parse().expect("Invalid integer");
            println!("{}", format_i64_vec(&shrink_int(x)));
        }
        "shrink-bool" => {
            match args[2].as_str() {
                "true" => println!("[false]"),
                "false" => println!("[]"),
                _ => {
                    eprintln!("Expected 'true' or 'false'");
                    std::process::exit(1);
                }
            }
        }
        "shrink-vec" => {
            let xs: Vec<i64> = if args[2] == "empty" {
                vec![]
            } else {
                args[2]
                    .split(',')
                    .map(|s| s.trim().parse().expect("Invalid integer"))
                    .collect()
            };
            let result = shrink_vec(&xs, true);
            let formatted: Vec<String> = result.iter().map(|v| format_i64_vec(v)).collect();
            println!("[{}]", formatted.join(", "));
        }
        "shrink-vec-int" => {
            let xs: Vec<i64> = if args[2] == "empty" {
                vec![]
            } else {
                args[2]
                    .split(',')
                    .map(|s| s.trim().parse().expect("Invalid integer"))
                    .collect()
            };
            let result = shrink_vec(&xs, false);
            let formatted: Vec<String> = result.iter().map(|v| format_i64_vec(v)).collect();
            println!("[{}]", formatted.join(", "));
        }
        cmd => {
            eprintln!("Unknown command: {}", cmd);
            std::process::exit(1);
        }
    }
}
