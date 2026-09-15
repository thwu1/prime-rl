
use std::collections::HashMap;
use std::env;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Read, Write as IoWrite};
use std::process;

// ==================== FST Data Structures ====================

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
struct FstNode {
    is_final: bool,
    final_output: u64,
    trans: Vec<(u8, u64, usize)>, // (input_byte, output, target_node_id)
}

impl FstNode {
    fn find_input(&self, b: u8) -> Option<usize> {
        self.trans.iter().position(|t| t.0 == b)
    }
}

struct Fst {
    nodes: Vec<FstNode>,
    root: usize,
    num_keys: u64,
}

impl Fst {
    fn contains(&self, key: &[u8]) -> bool {
        let mut nid = self.root;
        for &b in key {
            match self.nodes[nid].find_input(b) {
                Some(idx) => nid = self.nodes[nid].trans[idx].2,
                None => return false,
            }
        }
        self.nodes[nid].is_final
    }

    fn get(&self, key: &[u8]) -> Option<u64> {
        let mut nid = self.root;
        let mut out = 0u64;
        for &b in key {
            match self.nodes[nid].find_input(b) {
                Some(idx) => {
                    out += self.nodes[nid].trans[idx].1;
                    nid = self.nodes[nid].trans[idx].2;
                }
                None => return None,
            }
        }
        if self.nodes[nid].is_final {
            Some(out + self.nodes[nid].final_output)
        } else {
            None
        }
    }

    fn enumerate_all(&self) -> Vec<(Vec<u8>, u64)> {
        let mut results = Vec::new();
        let mut stack: Vec<(usize, Vec<u8>, u64)> = vec![(self.root, vec![], 0)];
        while let Some((nid, key, out)) = stack.pop() {
            let node = &self.nodes[nid];
            if node.is_final {
                results.push((key.clone(), out + node.final_output));
            }
            for &(inp, tout, target) in node.trans.iter().rev() {
                let mut nk = key.clone();
                nk.push(inp);
                stack.push((target, nk, out + tout));
            }
        }
        results
    }

    fn keys_filtered(
        &self,
        prefix: Option<&[u8]>,
        ge: Option<&[u8]>,
        le: Option<&[u8]>,
    ) -> Vec<(Vec<u8>, u64)> {
        self.enumerate_all()
            .into_iter()
            .filter(|(k, _)| {
                if let Some(p) = prefix {
                    if !k.starts_with(p) {
                        return false;
                    }
                }
                if let Some(lo) = ge {
                    if k.as_slice() < lo {
                        return false;
                    }
                }
                if let Some(hi) = le {
                    if k.as_slice() > hi {
                        return false;
                    }
                }
                true
            })
            .collect()
    }

    // ---- Serialization ----

    fn write_to<W: IoWrite>(&self, w: &mut W) -> io::Result<()> {
        w.write_all(b"FST1")?;
        w.write_all(&(self.nodes.len() as u64).to_le_bytes())?;
        w.write_all(&(self.root as u64).to_le_bytes())?;
        w.write_all(&self.num_keys.to_le_bytes())?;
        for node in &self.nodes {
            w.write_all(&[node.is_final as u8])?;
            w.write_all(&node.final_output.to_le_bytes())?;
            w.write_all(&(node.trans.len() as u32).to_le_bytes())?;
            for &(inp, out, tgt) in &node.trans {
                w.write_all(&[inp])?;
                w.write_all(&out.to_le_bytes())?;
                w.write_all(&(tgt as u64).to_le_bytes())?;
            }
        }
        Ok(())
    }

    fn read_from<R: Read>(r: &mut R) -> io::Result<Self> {
        let mut magic = [0u8; 4];
        r.read_exact(&mut magic)?;
        if &magic != b"FST1" {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "bad magic"));
        }
        let mut b8 = [0u8; 8];
        r.read_exact(&mut b8)?;
        let nn = u64::from_le_bytes(b8) as usize;
        r.read_exact(&mut b8)?;
        let root = u64::from_le_bytes(b8) as usize;
        r.read_exact(&mut b8)?;
        let num_keys = u64::from_le_bytes(b8);

        let mut nodes = Vec::with_capacity(nn);
        for _ in 0..nn {
            let mut f = [0u8; 1];
            r.read_exact(&mut f)?;
            let is_final = f[0] != 0;
            r.read_exact(&mut b8)?;
            let final_output = u64::from_le_bytes(b8);
            let mut b4 = [0u8; 4];
            r.read_exact(&mut b4)?;
            let nt = u32::from_le_bytes(b4) as usize;
            let mut trans = Vec::with_capacity(nt);
            for _ in 0..nt {
                let mut ib = [0u8; 1];
                r.read_exact(&mut ib)?;
                r.read_exact(&mut b8)?;
                let out = u64::from_le_bytes(b8);
                r.read_exact(&mut b8)?;
                let tgt = u64::from_le_bytes(b8) as usize;
                trans.push((ib[0], out, tgt));
            }
            nodes.push(FstNode {
                is_final,
                final_output,
                trans,
            });
        }
        Ok(Fst {
            nodes,
            root,
            num_keys,
        })
    }
}

// ==================== FST Builder ====================

struct UnfinishedNode {
    is_final: bool,
    final_output: u64,
    compiled_trans: Vec<(u8, u64, usize)>,
    last_input: Option<u8>,
    last_output: u64,
}

impl UnfinishedNode {
    fn new() -> Self {
        UnfinishedNode {
            is_final: false,
            final_output: 0,
            compiled_trans: Vec::new(),
            last_input: None,
            last_output: 0,
        }
    }
}

fn common_prefix_len(a: &[u8], b: &[u8]) -> usize {
    a.iter().zip(b.iter()).take_while(|(x, y)| x == y).count()
}

struct FstBuilder {
    stack: Vec<UnfinishedNode>,
    registry: HashMap<FstNode, usize>,
    compiled: Vec<FstNode>,
    prev_key: Vec<u8>,
    num_keys: u64,
}

impl FstBuilder {
    fn new() -> Self {
        FstBuilder {
            stack: vec![UnfinishedNode::new()],
            registry: HashMap::new(),
            compiled: Vec::new(),
            prev_key: Vec::new(),
            num_keys: 0,
        }
    }

    fn insert(&mut self, key: &[u8], value: u64) {
        if self.num_keys > 0 {
            assert!(
                key > self.prev_key.as_slice(),
                "Keys must be in strictly ascending lexicographic order"
            );
        }

        let plen = common_prefix_len(&self.prev_key, key);
        self.freeze_tail(plen);

        // Add new unfinished nodes for each byte after the shared prefix
        for i in plen..key.len() {
            self.stack.push(UnfinishedNode::new());
            let parent = self.stack.len() - 2;
            self.stack[parent].last_input = Some(key[i]);
            self.stack[parent].last_output = 0;
        }

        // Mark the deepest node as final
        let last = self.stack.len() - 1;
        self.stack[last].is_final = true;

        // --- Output management: prefix / push-down ---
        let mut remaining = value;
        for i in 0..plen {
            let cur = self.stack[i].last_output;
            let common = std::cmp::min(cur, remaining);
            let remainder = cur - common;
            self.stack[i].last_output = common;
            if remainder > 0 {
                self.push_output(i + 1, remainder);
            }
            remaining -= common;
        }

        if plen < key.len() {
            // Set output on the first new transition
            self.stack[plen].last_output = remaining;
        } else {
            // key == shared prefix (only for empty-key first insertion)
            self.stack[plen].final_output = remaining;
        }

        self.prev_key = key.to_vec();
        self.num_keys += 1;
    }

    fn push_output(&mut self, node_idx: usize, amount: u64) {
        let node = &mut self.stack[node_idx];
        for t in &mut node.compiled_trans {
            t.1 += amount;
        }
        if node.last_input.is_some() {
            node.last_output += amount;
        }
        if node.is_final {
            node.final_output += amount;
        }
    }

    fn freeze_tail(&mut self, prefix_len: usize) {
        let len = self.stack.len();
        for i in (prefix_len + 1..len).rev() {
            let child = FstNode {
                is_final: self.stack[i].is_final,
                final_output: self.stack[i].final_output,
                trans: self.stack[i].compiled_trans.clone(),
            };

            let cid = if let Some(&id) = self.registry.get(&child) {
                id
            } else {
                let id = self.compiled.len();
                self.registry.insert(child.clone(), id);
                self.compiled.push(child);
                id
            };

            let parent = i - 1;
            let inp = self.stack[parent].last_input.unwrap();
            let out = self.stack[parent].last_output;
            self.stack[parent].compiled_trans.push((inp, out, cid));
            self.stack[parent].last_input = None;
            self.stack[parent].last_output = 0;
        }
        self.stack.truncate(prefix_len + 1);
    }

    fn finish(mut self) -> Fst {
        self.freeze_tail(0);

        let root_node = FstNode {
            is_final: self.stack[0].is_final,
            final_output: self.stack[0].final_output,
            trans: self.stack[0].compiled_trans.clone(),
        };

        let root_id = if let Some(&id) = self.registry.get(&root_node) {
            id
        } else {
            let id = self.compiled.len();
            self.compiled.push(root_node);
            id
        };

        Fst {
            nodes: self.compiled,
            root: root_id,
            num_keys: self.num_keys,
        }
    }
}

// ==================== Levenshtein Automaton ====================

type NfaSt = (usize, usize); // (position_in_query, error_count)

fn eps_closure(states: &[NfaSt], qlen: usize, maxd: usize) -> Vec<NfaSt> {
    let mut res: Vec<NfaSt> = states.to_vec();
    let mut i = 0;
    while i < res.len() {
        let (pos, err) = res[i];
        if pos < qlen && err < maxd {
            let ns = (pos + 1, err + 1);
            if !res.contains(&ns) {
                res.push(ns);
            }
        }
        i += 1;
    }
    res.sort();
    res.dedup();
    res
}

fn nfa_step(states: &[NfaSt], byte: u8, query: &[u8], maxd: usize) -> Vec<NfaSt> {
    let mut next: Vec<NfaSt> = Vec::new();
    for &(pos, err) in states {
        if pos < query.len() {
            if byte == query[pos] {
                // Match
                let s = (pos + 1, err);
                if !next.contains(&s) {
                    next.push(s);
                }
            } else if err < maxd {
                // Substitution
                let s = (pos + 1, err + 1);
                if !next.contains(&s) {
                    next.push(s);
                }
            }
        }
        // Insertion in target (extra byte not in query)
        if err < maxd {
            let s = (pos, err + 1);
            if !next.contains(&s) {
                next.push(s);
            }
        }
    }
    next
}

struct LevDfa {
    trans: Vec<HashMap<u8, usize>>,
    is_accept: Vec<bool>,
    min_dist: Vec<usize>,
}

impl LevDfa {
    fn build(query: &[u8], maxd: usize) -> Self {
        let start = eps_closure(&[(0, 0)], query.len(), maxd);

        let mut dfa_states: Vec<Vec<NfaSt>> = vec![start.clone()];
        let mut state_map: HashMap<Vec<NfaSt>, usize> = HashMap::new();
        state_map.insert(start, 0);

        let mut trans: Vec<HashMap<u8, usize>> = vec![HashMap::new()];
        let mut queue: Vec<usize> = vec![0];

        while let Some(cid) = queue.pop() {
            let cstate = dfa_states[cid].clone();
            for byte in 0..=255u8 {
                let next_nfa = nfa_step(&cstate, byte, query, maxd);
                if next_nfa.is_empty() {
                    continue;
                }
                let next = eps_closure(&next_nfa, query.len(), maxd);
                if next.is_empty() {
                    continue;
                }

                let nid = if let Some(&id) = state_map.get(&next) {
                    id
                } else {
                    let id = dfa_states.len();
                    state_map.insert(next.clone(), id);
                    dfa_states.push(next);
                    trans.push(HashMap::new());
                    queue.push(id);
                    id
                };
                trans[cid].insert(byte, nid);
            }
        }

        let qlen = query.len();
        let (is_accept, min_dist): (Vec<bool>, Vec<usize>) = dfa_states
            .iter()
            .map(|st| {
                let mut md = usize::MAX;
                for &(p, e) in st {
                    if p == qlen && e <= maxd && e < md {
                        md = e;
                    }
                }
                if md <= maxd {
                    (true, md)
                } else {
                    (false, 0)
                }
            })
            .unzip();

        LevDfa {
            trans,
            is_accept,
            min_dist,
        }
    }
}

// ==================== Fuzzy Search (intersection) ====================

fn fuzzy_search(fst: &Fst, query: &[u8], maxd: usize) -> Vec<(Vec<u8>, u64, usize)> {
    let dfa = LevDfa::build(query, maxd);
    let mut results: Vec<(Vec<u8>, u64, usize)> = Vec::new();

    // DFS: (fst_node_id, lev_dfa_state, key, accumulated_output)
    let mut stack: Vec<(usize, usize, Vec<u8>, u64)> =
        vec![(fst.root, 0, Vec::new(), 0)];

    while let Some((fid, lid, key, out)) = stack.pop() {
        let fnode = &fst.nodes[fid];

        // Check if both FST and Levenshtein accept here
        if fnode.is_final && dfa.is_accept[lid] {
            results.push((key.clone(), out + fnode.final_output, dfa.min_dist[lid]));
        }

        // Follow FST transitions that the Levenshtein DFA also allows
        for &(inp, tout, ftgt) in fnode.trans.iter().rev() {
            if let Some(&ltgt) = dfa.trans[lid].get(&inp) {
                let mut nk = key.clone();
                nk.push(inp);
                stack.push((ftgt, ltgt, nk, out + tout));
            }
        }
    }

    results.sort_by(|a, b| a.0.cmp(&b.0));
    results
}

// ==================== CLI ====================

fn load_fst(path: &str) -> Fst {
    let mut f = File::open(path).unwrap_or_else(|e| {
        eprintln!("Error opening {}: {}", path, e);
        process::exit(1);
    });
    Fst::read_from(&mut f).unwrap_or_else(|e| {
        eprintln!("Error reading FST: {}", e);
        process::exit(1);
    })
}

fn cmd_build(args: &[String]) {
    if args.len() < 2 {
        eprintln!("Usage: fst-tool build <input> <output>");
        process::exit(1);
    }
    let input_path = &args[0];
    let output_path = &args[1];

    let file = File::open(input_path).unwrap_or_else(|e| {
        eprintln!("Error opening {}: {}", input_path, e);
        process::exit(1);
    });
    let reader = BufReader::new(file);
    let mut builder = FstBuilder::new();

    for line in reader.lines() {
        let line = line.unwrap();
        if line.is_empty() {
            continue;
        }
        let mut parts = line.splitn(2, '\t');
        let key = parts.next().unwrap();
        let val_str = parts.next().unwrap_or("0");
        let val: u64 = val_str.parse().unwrap_or_else(|e| {
            eprintln!("Bad value '{}': {}", val_str, e);
            process::exit(1);
        });
        builder.insert(key.as_bytes(), val);
    }

    let fst = builder.finish();
    let mut out = File::create(output_path).unwrap_or_else(|e| {
        eprintln!("Error creating {}: {}", output_path, e);
        process::exit(1);
    });
    fst.write_to(&mut out).unwrap();
}

fn cmd_contains(args: &[String]) {
    if args.len() < 2 {
        eprintln!("Usage: fst-tool contains <fst> <key>");
        process::exit(1);
    }
    let fst = load_fst(&args[0]);
    let key = &args[1];
    println!("{}", fst.contains(key.as_bytes()));
}

fn cmd_get(args: &[String]) {
    if args.len() < 2 {
        eprintln!("Usage: fst-tool get <fst> <key>");
        process::exit(1);
    }
    let fst = load_fst(&args[0]);
    let key = &args[1];
    match fst.get(key.as_bytes()) {
        Some(v) => println!("{}", v),
        None => println!("NOT_FOUND"),
    }
}

fn cmd_keys(args: &[String]) {
    if args.is_empty() {
        eprintln!("Usage: fst-tool keys <fst> [--prefix <p>] [--ge <lo>] [--le <hi>]");
        process::exit(1);
    }
    let fst = load_fst(&args[0]);

    let mut prefix: Option<String> = None;
    let mut ge: Option<String> = None;
    let mut le: Option<String> = None;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--prefix" => {
                i += 1;
                prefix = Some(args[i].clone());
            }
            "--ge" => {
                i += 1;
                ge = Some(args[i].clone());
            }
            "--le" => {
                i += 1;
                le = Some(args[i].clone());
            }
            _ => {
                eprintln!("Unknown flag: {}", args[i]);
                process::exit(1);
            }
        }
        i += 1;
    }

    let results = fst.keys_filtered(
        prefix.as_ref().map(|s| s.as_bytes()),
        ge.as_ref().map(|s| s.as_bytes()),
        le.as_ref().map(|s| s.as_bytes()),
    );

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for (k, v) in results {
        let key_str = String::from_utf8_lossy(&k);
        writeln!(out, "{}\t{}", key_str, v).unwrap();
    }
}

fn cmd_fuzzy(args: &[String]) {
    if args.len() < 3 {
        eprintln!("Usage: fst-tool fuzzy <fst> <query> <distance>");
        process::exit(1);
    }
    let fst = load_fst(&args[0]);
    let query = &args[1];
    let maxd: usize = args[2].parse().unwrap_or_else(|e| {
        eprintln!("Bad distance '{}': {}", args[2], e);
        process::exit(1);
    });

    let results = fuzzy_search(&fst, query.as_bytes(), maxd);
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for (k, v, d) in results {
        let key_str = String::from_utf8_lossy(&k);
        writeln!(out, "{}\t{}\t{}", key_str, v, d).unwrap();
    }
}

fn cmd_info(args: &[String]) {
    if args.is_empty() {
        eprintln!("Usage: fst-tool info <fst>");
        process::exit(1);
    }
    let fst = load_fst(&args[0]);
    println!("keys: {}", fst.num_keys);
    println!("nodes: {}", fst.nodes.len());
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: fst-tool <command> [args...]");
        eprintln!("Commands: build, contains, get, keys, fuzzy, info");
        process::exit(1);
    }

    let cmd = &args[1];
    let rest = &args[2..];

    match cmd.as_str() {
        "build" => cmd_build(rest),
        "contains" => cmd_contains(rest),
        "get" => cmd_get(rest),
        "keys" => cmd_keys(rest),
        "fuzzy" => cmd_fuzzy(rest),
        "info" => cmd_info(rest),
        _ => {
            eprintln!("Unknown command: {}", cmd);
            process::exit(1);
        }
    }
}
