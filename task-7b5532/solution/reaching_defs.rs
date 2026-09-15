
use std::fs;
use std::io::{BufRead, BufReader};

use datafrog_engine::{
    leapjoin_into, ExtendAnti, ExtendWith, FilterAnti, Relation, Variable,
};

fn load_pairs(path: &str) -> Vec<(u32, u32)> {
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

fn load_nodes(path: &str) -> Vec<u32> {
    let mut nodes: Vec<u32> = BufReader::new(fs::File::open(path).unwrap())
        .lines()
        .map(|l| l.unwrap().trim().parse::<u32>().unwrap())
        .collect();
    nodes.sort();
    nodes.dedup();
    nodes
}

fn main() {
    let cfg_edges = load_pairs("/app/data/cfg.txt");
    let gen_pairs = load_pairs("/app/data/gen.txt");
    let kill_pairs = load_pairs("/app/data/kill.txt");
    let block_nodes = load_nodes("/app/data/block.txt");

    // Reaching definitions:
    //   rd(x, d) :- gen(x, d).
    //   rd(y, d) :- rd(x, d), !block(x), cfg(x, y), !kill(y, d).
    //
    // Source: rd Variable with (node, def) tuples.
    // Leapers:
    //   FilterAnti: !block(x) — extracts x from (x,d), checks block set
    //   ExtendWith: cfg(x, y) — extracts x from (x,d), proposes y from cfg
    //   ExtendAnti: !kill(y, d) — extracts d from (x,d), removes y where (d,y) in kill_by_def
    //
    // Output: (y, d) tuples fed back into rd.

    // CFG indexed by source node: sorted (src, dst) pairs
    let cfg_rel = Relation::new(cfg_edges);

    // Kill indexed by definition: sorted (def, node) pairs
    let kill_by_def = Relation::new(
        kill_pairs
            .iter()
            .map(|&(node, def)| (def, node))
            .collect(),
    );

    let rd_var: Variable<(u32, u32)> = Variable::new();

    // Initialize: rd(x, d) :- gen(x, d)
    rd_var.insert(Relation::new(gen_pairs));

    loop {
        let c = rd_var.changed();
        if !c {
            break;
        }

        // rd(y, d) :- rd(x, d), !block(x), cfg(x, y), !kill(y, d)
        leapjoin_into(
            &rd_var,
            &mut [
                &mut FilterAnti::new(&block_nodes, |&(x, _d): &(u32, u32)| x),
                &mut ExtendWith::new(&cfg_rel.elements, |&(x, _d): &(u32, u32)| x),
                &mut ExtendAnti::new(&kill_by_def.elements, |&(_x, d): &(u32, u32)| d),
            ],
            &rd_var,
            |&(_x, d), &y| (y, d),
        );
    }

    let result = rd_var.complete();
    let count = result.len();

    fs::create_dir_all("/app/output").ok();
    fs::write("/app/output/rd_count.txt", count.to_string()).unwrap();
    eprintln!("Reaching definitions: {} pairs", count);
}
