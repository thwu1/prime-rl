
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader};

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

    // Collect all nodes appearing in any edge
    let mut all_nodes: HashSet<u32> = HashSet::new();
    for &(a, b) in &edges {
        all_nodes.insert(a);
        all_nodes.insert(b);
    }

    // Step 1: Compute transitive closure using the engine.
    //   reach(x, y) :- edge(x, y).
    //   reach(x, z) :- reach(x, y), edge(y, z).
    //
    // The engine's join_into performs a semi-naive equijoin on the first
    // tuple component. We store reach tuples as (y, x) — keyed by the
    // intermediate node y — so the join with edges (y, z) produces (z, x).
    let reach_var: Variable<(u32, u32)> = Variable::new();
    let edge_var: Variable<(u32, u32)> = Variable::new();

    // Initialize: reach(x, y) stored as (y, x)
    reach_var.insert(Relation::new(
        edges.iter().map(|&(x, y)| (y, x)).collect(),
    ));
    edge_var.insert(Relation::new(edges));

    loop {
        let c1 = reach_var.changed();
        let c2 = edge_var.changed();
        if !c1 && !c2 {
            break;
        }
        // (y, x) join (y, z) -> (z, x)
        join_into(&reach_var, &edge_var, &reach_var, |_y, &x, &z| (z, x));
    }

    // Extract completed TC: (y, x) means x can reach y.
    // Convert to forward direction: (x, y) means x reaches y.
    let tc_pairs = reach_var.complete();
    let reach_set: HashSet<(u32, u32)> =
        tc_pairs.iter().map(|&(y, x)| (x, y)).collect();

    // Step 2: Identify SCCs via mutual reachability.
    // Two nodes a, b are in the same SCC iff reach(a,b) AND reach(b,a).
    // Use min-representative grouping: for each node, its SCC representative
    // is the minimum node ID among all mutually reachable nodes (incl. itself).
    let mut scc_id: HashMap<u32, u32> = HashMap::new();
    for &n in &all_nodes {
        let mut rep = n;
        for &m in &all_nodes {
            if m < rep
                && reach_set.contains(&(n, m))
                && reach_set.contains(&(m, n))
            {
                rep = m;
            }
        }
        scc_id.insert(n, rep);
    }

    // Step 3: Count distinct SCCs and find the largest.
    let mut sizes: HashMap<u32, usize> = HashMap::new();
    for &n in &all_nodes {
        *sizes.entry(scc_id[&n]).or_insert(0) += 1;
    }

    let scc_count = sizes.len();
    let largest_scc = sizes.values().copied().max().unwrap_or(0);

    fs::create_dir_all("/app/output").ok();
    fs::write("/app/output/scc_count.txt", scc_count.to_string()).unwrap();
    fs::write(
        "/app/output/largest_scc.txt",
        largest_scc.to_string(),
    )
    .unwrap();
    eprintln!("SCCs: {}, largest: {}", scc_count, largest_scc);
}
