use std::io::{self, BufRead, Write};
use vma_mgr::*;

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut mgr = VmaManager::new();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let op: serde_json::Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                let _ = writeln!(
                    out,
                    "{}",
                    serde_json::json!({"error": format!("parse_error: {}", e)})
                );
                continue;
            }
        };
        let result = dispatch(&mut mgr, &op);
        let _ = writeln!(out, "{}", result);
    }
}

fn parse_prot(s: &str) -> Option<Protection> {
    if s.len() != 3 {
        return None;
    }
    let b = s.as_bytes();
    Some(Protection {
        read: b[0] == b'r',
        write: b[1] == b'w',
        exec: b[2] == b'x',
    })
}

fn prot_to_str(p: &Protection) -> String {
    format!(
        "{}{}{}",
        if p.read { 'r' } else { '-' },
        if p.write { 'w' } else { '-' },
        if p.exec { 'x' } else { '-' },
    )
}

fn vma_to_json(v: &VmaInfo) -> serde_json::Value {
    serde_json::json!({
        "start": v.start,
        "end": v.end,
        "prot": prot_to_str(&v.prot),
        "map_type": match v.map_type {
            MapType::Private => "private",
            MapType::Shared => "shared",
        },
    })
}

fn dispatch(mgr: &mut VmaManager, op: &serde_json::Value) -> serde_json::Value {
    match op["op"].as_str().unwrap_or("") {
        "mmap" => {
            let addr = if op["addr"].is_null() {
                None
            } else {
                op["addr"].as_u64()
            };
            let len = op["len"].as_u64().unwrap_or(0);
            let prot = parse_prot(op["prot"].as_str().unwrap_or("---"))
                .unwrap_or(Protection {
                    read: false,
                    write: false,
                    exec: false,
                });
            let map_type = match op["map_type"].as_str().unwrap_or("private") {
                "shared" => MapType::Shared,
                _ => MapType::Private,
            };
            let fixed = op["fixed"].as_bool().unwrap_or(false);
            match mgr.mmap(addr, len, prot, map_type, fixed) {
                Ok(base) => serde_json::json!({"ok": {"addr": base}}),
                Err(e) => serde_json::json!({"error": e.to_string()}),
            }
        }
        "munmap" => {
            let addr = op["addr"].as_u64().unwrap_or(0);
            let len = op["len"].as_u64().unwrap_or(0);
            match mgr.munmap(addr, len) {
                Ok(()) => serde_json::json!({"ok": null}),
                Err(e) => serde_json::json!({"error": e.to_string()}),
            }
        }
        "mprotect" => {
            let addr = op["addr"].as_u64().unwrap_or(0);
            let len = op["len"].as_u64().unwrap_or(0);
            let prot = parse_prot(op["prot"].as_str().unwrap_or("---"))
                .unwrap_or(Protection {
                    read: false,
                    write: false,
                    exec: false,
                });
            match mgr.mprotect(addr, len, prot) {
                Ok(()) => serde_json::json!({"ok": null}),
                Err(e) => serde_json::json!({"error": e.to_string()}),
            }
        }
        "query" => {
            let addr = op["addr"].as_u64().unwrap_or(0);
            match mgr.query(addr) {
                Some(vma) => serde_json::json!({"ok": {"vma": vma_to_json(&vma)}}),
                None => serde_json::json!({"ok": {"vma": null}}),
            }
        }
        "dump" => {
            let vmas = mgr.dump();
            let arr: Vec<serde_json::Value> =
                vmas.iter().map(|v| vma_to_json(v)).collect();
            serde_json::json!({"ok": {"vmas": arr}})
        }
        _ => serde_json::json!({"error": "unknown_operation"}),
    }
}
