
use std::fs;
use std::io::{BufRead, BufReader};

use datafrog_engine::{leapjoin_into, ExtendWith, Relation, Variable};

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

    // Triangle counting:
    //   triangle(a, b, c) :- edge(a, b), edge(b, c), edge(a, c).
    //
    // Source: Variable containing edges (a, b).
    // Extend with c using two ExtendWith leapers on the edge relation.

    let edge_rel = Relation::new(edges.clone());

    let edges_var: Variable<(u32, u32)> = Variable::new();
    let tri_var: Variable<(u32, u32, u32)> = Variable::new();

    edges_var.insert(Relation::new(edges));

    loop {
        let c1 = edges_var.changed();
        let c2 = tri_var.changed();
        if !c1 && !c2 {
            break;
        }

        leapjoin_into(
            &edges_var,
            &mut [
                &mut ExtendWith::new(&edge_rel.elements, |&(_, b): &(u32, u32)| b),
                &mut ExtendWith::new(&edge_rel.elements, |&(_, b): &(u32, u32)| b),
            ],
            &tri_var,
            |&(a, b), &c| (a, b, c),
        );
    }

    let result = tri_var.complete();
    let count = result.len();

    fs::create_dir_all("/app/output").ok();
    fs::write("/app/output/tri_count.txt", count.to_string()).unwrap();
    eprintln!("Triangles: {}", count);
}
