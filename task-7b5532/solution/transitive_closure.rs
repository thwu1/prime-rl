
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

    // Transitive closure:
    //   reach(x, y) :- edge(x, y).
    //   reach(x, z) :- reach(x, y), edge(y, z).
    //
    // Store reach keyed by intermediate node y: tuples are (y, x)
    // meaning "x can reach y". Store edges keyed by source: (src, dst).
    // Join on y=src: (y, x) ⋈ (y, z) → output (z, x) meaning "x can reach z".

    let reach_var: Variable<(u32, u32)> = Variable::new();
    let edge_var: Variable<(u32, u32)> = Variable::new();

    // Initialize: reach(x, y) :- edge(x, y). Stored as (y, x).
    reach_var.insert(Relation::new(
        edges.iter().map(|&(x, y)| (y, x)).collect(),
    ));
    // Edges stored as (src, dst).
    edge_var.insert(Relation::new(edges));

    loop {
        let c1 = reach_var.changed();
        let c2 = edge_var.changed();
        if !c1 && !c2 {
            break;
        }

        // reach(y, x) ⋈ edge(y, z) → reach(z, x)
        join_into(&reach_var, &edge_var, &reach_var, |_y, &x, &z| (z, x));
    }

    let result = reach_var.complete();
    let count = result.len();

    fs::create_dir_all("/app/output").ok();
    fs::write("/app/output/tc_count.txt", count.to_string()).unwrap();
    eprintln!("Transitive closure: {} reachable pairs", count);
}
