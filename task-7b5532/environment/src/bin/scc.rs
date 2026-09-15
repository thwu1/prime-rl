
use std::fs;
use std::io::{BufRead, BufReader};

// The engine library provides the building blocks for relational computation.
// Study /app/src/bin/transitive_closure.rs for API usage patterns.
#[allow(unused_imports)]
use datafrog_engine::{join_into, Relation, Variable};

fn load_edges(path: &str) -> Vec<(u32, u32)> {
    BufReader::new(fs::File::open(path).unwrap())
        .lines()
        .map(|l| {
            let l = l.unwrap();
            let mut parts = l.split_whitespace();
            let a: u32 = parts.next().unwrap().parse().unwrap();
            let b: u32 = parts.next().unwrap().parse().unwrap();
            (a, b)
        })
        .collect()
}

fn main() {
    let edges = load_edges("/app/data/edges.txt");

    // Strongly Connected Components via mutual reachability.
    //
    // Datalog rules for transitive closure:
    //   reach(x, y) :- edge(x, y).
    //   reach(x, z) :- reach(x, y), edge(y, z).
    //
    // SCC definition:
    //   same_scc(x, y) :- reach(x, y), reach(y, x).
    //   Every node belongs to exactly one SCC.
    //   Nodes with no mutual reachability partner form singleton SCCs.
    //
    // Required outputs:
    //   /app/output/scc_count.txt   — total number of distinct SCCs
    //   /app/output/largest_scc.txt — size (node count) of the largest SCC

    // TODO: implement SCC computation using the datafrog_engine library.
    // Remember: all nodes appearing in any edge must be accounted for.

    let _ = edges; // suppress unused warning

    let scc_count: usize = 0;
    let largest_scc: usize = 0;

    fs::create_dir_all("/app/output").ok();
    fs::write("/app/output/scc_count.txt", scc_count.to_string()).unwrap();
    fs::write("/app/output/largest_scc.txt", largest_scc.to_string()).unwrap();
    eprintln!("SCCs: {}, largest: {}", scc_count, largest_scc);
}
