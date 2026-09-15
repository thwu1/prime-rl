use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{self, BufRead, BufReader, Write as IoWrite};
use std::process;


// ============================================================
// FST Data Structures
// ============================================================

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct Transition {
    input: u8,
    output: u64,
    target: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct FstState {
    transitions: Vec<Transition>,
    is_final: bool,
    final_output: u64,
}

// ============================================================
// Builder Internals
// ============================================================

struct UnfinishedTransition {
    input: u8,
    output: u64,
    target: Option<usize>,
}

struct UnfinishedState {
    transitions: Vec<UnfinishedTransition>,
    is_final: bool,
    final_output: u64,
}

impl UnfinishedState {
    fn new() -> Self {
        Self {
            transitions: Vec::new(),
            is_final: false,
            final_output: 0,
        }
    }

    fn last_output(&self) -> u64 {
        self.transitions.last().map_or(0, |t| t.output)
    }

    fn set_last_output(&mut self, val: u64) {
        if let Some(t) = self.transitions.last_mut() {
            t.output = val;
        }
    }

    fn set_last_target(&mut self, target: usize) {
        if let Some(t) = self.transitions.last_mut() {
            t.target = Some(target);
        }
    }

    fn add_transition(&mut self, input: u8, output: u64) {
        self.transitions.push(UnfinishedTransition {
            input,
            output,
            target: None,
        });
    }
}

// ============================================================
// FstBuilder — Incremental Construction from Sorted Keys
// ============================================================

struct FstBuilder {
    compiled: Vec<FstState>,
    unfinished: Vec<UnfinishedState>,
    registry: HashMap<FstState, usize>,
    prev_key: Vec<u8>,
    num_keys: u64,
}

impl FstBuilder {
    fn new() -> Self {
        Self {
            compiled: Vec::new(),
            unfinished: vec![UnfinishedState::new()],
            registry: HashMap::new(),
            prev_key: Vec::new(),
            num_keys: 0,
        }
    }

    fn insert(&mut self, key: &[u8], value: u64) -> Result<(), String> {
        if !self.prev_key.is_empty() && key <= self.prev_key.as_slice() {
            return Err(format!(
                "keys out of order: {:?} <= {:?}",
                String::from_utf8_lossy(key),
                String::from_utf8_lossy(&self.prev_key)
            ));
        }

        let plen = common_prefix_len(&self.prev_key, key);

        self.freeze_tail(plen);

        let suffix_out = self.redistribute(value, plen);

        for i in plen..key.len() {
            let out = if i == plen { suffix_out } else { 0 };
            self.unfinished.last_mut().unwrap().add_transition(key[i], out);
            self.unfinished.push(UnfinishedState::new());
        }

        self.unfinished.last_mut().unwrap().is_final = true;

        self.prev_key = key.to_vec();
        self.num_keys += 1;
        Ok(())
    }

    fn freeze_tail(&mut self, keep: usize) {
        while self.unfinished.len() > keep + 1 {
            let state = self.unfinished.pop().unwrap();
            let id = self.compile(state);
            self.unfinished.last_mut().unwrap().set_last_target(id);
        }
    }

    fn redistribute(&mut self, value: u64, plen: usize) -> u64 {
        let mut rem = value;
        for i in 0..plen {
            let old = self.unfinished[i].last_output();
            let common = old.min(rem);
            self.unfinished[i].set_last_output(common);
            let diff = old - common;
            if diff > 0 {
                for t in &mut self.unfinished[i + 1].transitions {
                    t.output += diff;
                }
                if self.unfinished[i + 1].is_final {
                    self.unfinished[i + 1].final_output += diff;
                }
            }
            rem -= common;
        }
        rem
    }

    fn compile(&mut self, state: UnfinishedState) -> usize {
        let compiled = FstState {
            transitions: state
                .transitions
                .into_iter()
                .map(|t| Transition {
                    input: t.input,
                    output: t.output,
                    target: t.target.expect("unresolved transition target"),
                })
                .collect(),
            is_final: state.is_final,
            final_output: state.final_output,
        };
        if let Some(&id) = self.registry.get(&compiled) {
            id
        } else {
            let id = self.compiled.len();
            self.registry.insert(compiled.clone(), id);
            self.compiled.push(compiled);
            id
        }
    }

    fn finish(mut self) -> Fst {
        self.freeze_tail(0);
        let root = self.unfinished.pop().unwrap();
        let root_id = self.compile(root);
        Fst {
            states: self.compiled,
            root: root_id,
            num_keys: self.num_keys,
        }
    }
}

fn common_prefix_len(a: &[u8], b: &[u8]) -> usize {
    a.iter().zip(b.iter()).take_while(|(x, y)| x == y).count()
}

// ============================================================
// Fst — Queryable Finite State Transducer
// ============================================================

struct Fst {
    states: Vec<FstState>,
    root: usize,
    num_keys: u64,
}

impl Fst {
    fn contains(&self, key: &[u8]) -> bool {
        let mut sid = self.root;
        for &b in key {
            match self.states[sid].transitions.iter().find(|t| t.input == b) {
                Some(t) => sid = t.target,
                None => return false,
            }
        }
        self.states[sid].is_final
    }

    fn get(&self, key: &[u8]) -> Option<u64> {
        let mut sid = self.root;
        let mut out = 0u64;
        for &b in key {
            match self.states[sid].transitions.iter().find(|t| t.input == b) {
                Some(t) => {
                    out += t.output;
                    sid = t.target;
                }
                None => return None,
            }
        }
        let s = &self.states[sid];
        if s.is_final {
            Some(out + s.final_output)
        } else {
            None
        }
    }

    fn enumerate_all(&self, results: &mut Vec<(Vec<u8>, u64)>) {
        self.enum_dfs(self.root, &mut Vec::new(), 0, results);
    }

    fn enum_dfs(
        &self,
        sid: usize,
        key: &mut Vec<u8>,
        acc: u64,
        results: &mut Vec<(Vec<u8>, u64)>,
    ) {
        let s = &self.states[sid];
        if s.is_final {
            results.push((key.clone(), acc + s.final_output));
        }
        for t in &s.transitions {
            key.push(t.input);
            self.enum_dfs(t.target, key, acc + t.output, results);
            key.pop();
        }
    }

    fn range(&self, ge: Option<&[u8]>, le: Option<&[u8]>) -> Vec<(Vec<u8>, u64)> {
        let mut all = Vec::new();
        self.enumerate_all(&mut all);
        all.into_iter()
            .filter(|(k, _)| {
                ge.map_or(true, |g| k.as_slice() >= g)
                    && le.map_or(true, |l| k.as_slice() <= l)
            })
            .collect()
    }

    fn prefix_search(&self, prefix: &[u8]) -> Vec<(Vec<u8>, u64)> {
        let mut sid = self.root;
        let mut acc = 0u64;
        let mut key_prefix = Vec::new();
        for &b in prefix {
            match self.states[sid].transitions.iter().find(|t| t.input == b) {
                Some(t) => {
                    acc += t.output;
                    sid = t.target;
                    key_prefix.push(b);
                }
                None => return Vec::new(),
            }
        }
        let mut results = Vec::new();
        self.enum_dfs(sid, &mut key_prefix, acc, &mut results);
        results
    }

    fn fuzzy(&self, query: &[u8], max_dist: u32) -> Vec<(Vec<u8>, u64)> {
        let mut results = Vec::new();
        let row: Vec<u32> = (0..=query.len() as u32).collect();
        self.fuzzy_dfs(
            self.root,
            &row,
            query,
            max_dist,
            &mut Vec::new(),
            0,
            &mut results,
        );
        results
    }

    fn fuzzy_dfs(
        &self,
        sid: usize,
        prev: &[u32],
        query: &[u8],
        max_d: u32,
        key: &mut Vec<u8>,
        acc: u64,
        results: &mut Vec<(Vec<u8>, u64)>,
    ) {
        let s = &self.states[sid];
        if s.is_final && prev[query.len()] <= max_d {
            results.push((key.clone(), acc + s.final_output));
        }
        for t in &s.transitions {
            let mut row = Vec::with_capacity(query.len() + 1);
            row.push(prev[0] + 1);
            for j in 1..=query.len() {
                let cost = if query[j - 1] == t.input { 0 } else { 1 };
                let v = (row[j - 1] + 1)
                    .min(prev[j] + 1)
                    .min(prev[j - 1] + cost);
                row.push(v);
            }
            if *row.iter().min().unwrap() <= max_d {
                key.push(t.input);
                self.fuzzy_dfs(t.target, &row, query, max_d, key, acc + t.output, results);
                key.pop();
            }
        }
    }

    fn num_states(&self) -> usize {
        self.states.len()
    }

    fn num_transitions(&self) -> usize {
        self.states.iter().map(|s| s.transitions.len()).sum()
    }

    // ============================================================
    // Binary Serialization
    // ============================================================

    fn save(&self, path: &str) -> io::Result<()> {
        let mut buf = Vec::new();
        buf.extend_from_slice(b"FST\0");
        buf.extend_from_slice(&1u32.to_le_bytes());
        buf.extend_from_slice(&self.num_keys.to_le_bytes());
        buf.extend_from_slice(&(self.root as u64).to_le_bytes());
        buf.extend_from_slice(&(self.states.len() as u64).to_le_bytes());
        for s in &self.states {
            buf.push(s.is_final as u8);
            buf.extend_from_slice(&s.final_output.to_le_bytes());
            buf.extend_from_slice(&(s.transitions.len() as u32).to_le_bytes());
            for t in &s.transitions {
                buf.push(t.input);
                buf.extend_from_slice(&t.output.to_le_bytes());
                buf.extend_from_slice(&(t.target as u64).to_le_bytes());
            }
        }
        fs::write(path, &buf)
    }

    fn load(path: &str) -> io::Result<Self> {
        let data = fs::read(path)?;
        if data.len() < 32 || &data[0..4] != b"FST\0" {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid FST file"));
        }
        let mut p = 4;
        let _ver = u32::from_le_bytes(data[p..p + 4].try_into().unwrap());
        p += 4;
        let num_keys = u64::from_le_bytes(data[p..p + 8].try_into().unwrap());
        p += 8;
        let root = u64::from_le_bytes(data[p..p + 8].try_into().unwrap()) as usize;
        p += 8;
        let ns = u64::from_le_bytes(data[p..p + 8].try_into().unwrap()) as usize;
        p += 8;
        let mut states = Vec::with_capacity(ns);
        for _ in 0..ns {
            let is_final = data[p] != 0;
            p += 1;
            let fo = u64::from_le_bytes(data[p..p + 8].try_into().unwrap());
            p += 8;
            let nt = u32::from_le_bytes(data[p..p + 4].try_into().unwrap()) as usize;
            p += 4;
            let mut transitions = Vec::with_capacity(nt);
            for _ in 0..nt {
                let input = data[p];
                p += 1;
                let output = u64::from_le_bytes(data[p..p + 8].try_into().unwrap());
                p += 8;
                let target = u64::from_le_bytes(data[p..p + 8].try_into().unwrap()) as usize;
                p += 8;
                transitions.push(Transition {
                    input,
                    output,
                    target,
                });
            }
            states.push(FstState {
                transitions,
                is_final,
                final_output: fo,
            });
        }
        Ok(Fst {
            states,
            root,
            num_keys,
        })
    }
}

// ============================================================
// CLI
// ============================================================

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: fst-engine <command> [args...]");
        process::exit(1);
    }
    match args[1].as_str() {
        "build" => {
            if args.len() != 4 {
                eprintln!("Usage: fst-engine build <input> <output>");
                process::exit(1);
            }
            cmd_build(&args[2], &args[3]);
        }
        "contains" => {
            if args.len() != 4 {
                eprintln!("Usage: fst-engine contains <fst> <key>");
                process::exit(1);
            }
            cmd_contains(&args[2], &args[3]);
        }
        "get" => {
            if args.len() != 4 {
                eprintln!("Usage: fst-engine get <fst> <key>");
                process::exit(1);
            }
            cmd_get(&args[2], &args[3]);
        }
        "range" => {
            if args.len() < 3 {
                eprintln!("Usage: fst-engine range <fst> [--ge <key>] [--le <key>]");
                process::exit(1);
            }
            cmd_range(&args[2..]);
        }
        "fuzzy" => {
            if args.len() != 5 {
                eprintln!("Usage: fst-engine fuzzy <fst> <query> <max_dist>");
                process::exit(1);
            }
            cmd_fuzzy(&args[2], &args[3], &args[4]);
        }
        "prefix" => {
            if args.len() != 4 {
                eprintln!("Usage: fst-engine prefix <fst> <prefix>");
                process::exit(1);
            }
            cmd_prefix(&args[2], &args[3]);
        }
        "merge" => {
            if args.len() != 5 {
                eprintln!("Usage: fst-engine merge <fst1> <fst2> <output>");
                process::exit(1);
            }
            cmd_merge(&args[2], &args[3], &args[4]);
        }
        "stats" => {
            if args.len() != 3 {
                eprintln!("Usage: fst-engine stats <fst>");
                process::exit(1);
            }
            cmd_stats(&args[2]);
        }
        other => {
            eprintln!("Unknown command: {}", other);
            process::exit(1);
        }
    }
}

fn cmd_build(input: &str, output: &str) {
    let f = fs::File::open(input).unwrap_or_else(|e| {
        eprintln!("Error opening input: {}", e);
        process::exit(1);
    });
    let reader = BufReader::new(f);
    let mut builder = FstBuilder::new();

    for line_result in reader.lines() {
        let line = line_result.unwrap_or_else(|e| {
            eprintln!("Read error: {}", e);
            process::exit(1);
        });
        if line.is_empty() {
            continue;
        }
        let (key, val_str) = match line.split_once('\t') {
            Some(pair) => pair,
            None => {
                eprintln!("Invalid line (missing tab): {}", line);
                process::exit(1);
            }
        };
        let value: u64 = val_str.parse().unwrap_or_else(|_| {
            eprintln!("Invalid value: {}", val_str);
            process::exit(1);
        });
        if let Err(e) = builder.insert(key.as_bytes(), value) {
            eprintln!("Error: {}", e);
            process::exit(1);
        }
    }

    let fst = builder.finish();
    fst.save(output).unwrap_or_else(|e| {
        eprintln!("Error saving FST: {}", e);
        process::exit(1);
    });
}

fn cmd_contains(fst_path: &str, key: &str) {
    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });
    println!("{}", fst.contains(key.as_bytes()));
}

fn cmd_get(fst_path: &str, key: &str) {
    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });
    match fst.get(key.as_bytes()) {
        Some(v) => println!("{}", v),
        None => println!("NOT_FOUND"),
    }
}

fn cmd_range(args: &[String]) {
    let fst_path = &args[0];
    let mut ge: Option<String> = None;
    let mut le: Option<String> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--ge" => {
                if i + 1 >= args.len() {
                    eprintln!("--ge requires a value");
                    process::exit(1);
                }
                ge = Some(args[i + 1].clone());
                i += 2;
            }
            "--le" => {
                if i + 1 >= args.len() {
                    eprintln!("--le requires a value");
                    process::exit(1);
                }
                le = Some(args[i + 1].clone());
                i += 2;
            }
            other => {
                eprintln!("Unknown option: {}", other);
                process::exit(1);
            }
        }
    }

    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });

    let results = fst.range(
        ge.as_deref().map(|s| s.as_bytes()),
        le.as_deref().map(|s| s.as_bytes()),
    );

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for (k, v) in results {
        writeln!(out, "{}\t{}", String::from_utf8_lossy(&k), v).unwrap();
    }
}

fn cmd_fuzzy(fst_path: &str, query: &str, max_dist_str: &str) {
    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });
    let max_dist: u32 = max_dist_str.parse().unwrap_or_else(|_| {
        eprintln!("Invalid distance: {}", max_dist_str);
        process::exit(1);
    });
    let results = fst.fuzzy(query.as_bytes(), max_dist);

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for (k, v) in results {
        writeln!(out, "{}\t{}", String::from_utf8_lossy(&k), v).unwrap();
    }
}

fn cmd_prefix(fst_path: &str, prefix: &str) {
    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });
    let results = fst.prefix_search(prefix.as_bytes());

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for (k, v) in results {
        writeln!(out, "{}\t{}", String::from_utf8_lossy(&k), v).unwrap();
    }
}

fn cmd_merge(fst1_path: &str, fst2_path: &str, output_path: &str) {
    let fst1 = Fst::load(fst1_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST 1: {}", e);
        process::exit(1);
    });
    let fst2 = Fst::load(fst2_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST 2: {}", e);
        process::exit(1);
    });

    let mut entries1 = Vec::new();
    fst1.enumerate_all(&mut entries1);
    let mut entries2 = Vec::new();
    fst2.enumerate_all(&mut entries2);

    let mut merged = Vec::new();
    let (mut i, mut j) = (0, 0);
    while i < entries1.len() && j < entries2.len() {
        match entries1[i].0.cmp(&entries2[j].0) {
            std::cmp::Ordering::Less => {
                merged.push(entries1[i].clone());
                i += 1;
            }
            std::cmp::Ordering::Greater => {
                merged.push(entries2[j].clone());
                j += 1;
            }
            std::cmp::Ordering::Equal => {
                merged.push((entries1[i].0.clone(), entries1[i].1 + entries2[j].1));
                i += 1;
                j += 1;
            }
        }
    }
    while i < entries1.len() {
        merged.push(entries1[i].clone());
        i += 1;
    }
    while j < entries2.len() {
        merged.push(entries2[j].clone());
        j += 1;
    }

    let mut builder = FstBuilder::new();
    for (k, v) in &merged {
        if let Err(e) = builder.insert(k, *v) {
            eprintln!("Error building merged FST: {}", e);
            process::exit(1);
        }
    }
    let fst = builder.finish();
    fst.save(output_path).unwrap_or_else(|e| {
        eprintln!("Error saving merged FST: {}", e);
        process::exit(1);
    });
}

fn cmd_stats(fst_path: &str) {
    let size = fs::metadata(fst_path)
        .unwrap_or_else(|e| {
            eprintln!("Error: {}", e);
            process::exit(1);
        })
        .len();
    let fst = Fst::load(fst_path).unwrap_or_else(|e| {
        eprintln!("Error loading FST: {}", e);
        process::exit(1);
    });
    println!(
        "{{\"num_keys\":{},\"num_states\":{},\"num_transitions\":{},\"fst_size_bytes\":{}}}",
        fst.num_keys,
        fst.num_states(),
        fst.num_transitions(),
        size
    );
}
