use graph_engine::Graph;
use std::collections::HashMap;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        eprintln!(
            "Usage: {} <initial_edges> <operations> <num_batches> <output_dir>",
            args[0]
        );
        std::process::exit(1);
    }

    let initial_path = &args[1];
    let ops_path = &args[2];
    let num_batches: usize = args[3].parse().expect("num_batches must be integer");
    let output_dir = &args[4];

    // Load initial edges from CSV
    let mut initial_edges = Vec::new();
    {
        let file = File::open(initial_path).expect("cannot open initial edges file");
        let reader = BufReader::new(file);
        for (i, line) in reader.lines().enumerate() {
            if i == 0 {
                continue;
            }
            let line = line.unwrap();
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let parts: Vec<&str> = trimmed.split(',').collect();
            let u: u64 = parts[0].parse().unwrap();
            let v: u64 = parts[1].parse().unwrap();
            initial_edges.push((u, v));
        }
    }

    // Load operations grouped by batch_id
    let mut operations: HashMap<usize, Vec<(char, u64, u64)>> = HashMap::new();
    {
        let file = File::open(ops_path).expect("cannot open operations file");
        let reader = BufReader::new(file);
        for (i, line) in reader.lines().enumerate() {
            if i == 0 {
                continue;
            }
            let line = line.unwrap();
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let parts: Vec<&str> = trimmed.split(',').collect();
            let batch_id: usize = parts[0].parse().unwrap();
            let op: char = parts[1].chars().next().unwrap();
            let u: u64 = parts[2].parse().unwrap();
            let v: u64 = parts[3].parse().unwrap();
            operations.entry(batch_id).or_default().push((op, u, v));
        }
    }

    // Build graph and bootstrap incremental triangle counting via delta queries.
    // For each new edge (u,v), the triangle count changes by |N(u) & N(v)|
    // computed before inserting the edge.
    let mut graph = Graph::new();
    let mut total_tri: i64 = 0;
    let mut node_tri: HashMap<u64, i64> = HashMap::new();

    for &(u, v) in &initial_edges {
        let common = graph.common_neighbors(u, v);
        let delta = common.len() as i64;
        total_tri += delta;
        *node_tri.entry(u).or_default() += delta;
        *node_tri.entry(v).or_default() += delta;
        for &w in &common {
            *node_tri.entry(w).or_default() += 1;
        }
        graph.add_edge(u, v);
    }

    eprintln!(
        "Bootstrap complete: {} edges, {} triangles",
        graph.num_edges(),
        total_tri
    );

    // Process operation batches
    let mut tri_results: Vec<(usize, i64)> = Vec::new();
    for batch_id in 0..num_batches {
        if let Some(ops) = operations.get(&batch_id) {
            for &(op, u, v) in ops {
                let common = graph.common_neighbors(u, v);
                let delta = common.len() as i64;
                if op == '+' {
                    total_tri += delta;
                    *node_tri.entry(u).or_default() += delta;
                    *node_tri.entry(v).or_default() += delta;
                    for &w in &common {
                        *node_tri.entry(w).or_default() += 1;
                    }
                    graph.add_edge(u, v);
                } else {
                    total_tri -= delta;
                    *node_tri.entry(u).or_default() -= delta;
                    *node_tri.entry(v).or_default() -= delta;
                    graph.remove_edge(u, v);
                }
            }
        }
        tri_results.push((batch_id, total_tri));

        if (batch_id + 1) % 100 == 0 {
            eprintln!(
                "  Batch {}: triangles={}, edges={}",
                batch_id,
                total_tri,
                graph.num_edges()
            );
        }
    }

    // Write outputs
    std::fs::create_dir_all(output_dir).unwrap();

    // Triangle counts per batch
    {
        let path = format!("{}/triangle_counts.txt", output_dir);
        let file = File::create(&path).unwrap();
        let mut f = BufWriter::new(file);
        for &(bid, count) in &tri_results {
            writeln!(f, "{} {}", bid, count).unwrap();
        }
    }

    // Per-node triangle participation (final state)
    {
        let path = format!("{}/node_triangles.txt", output_dir);
        let file = File::create(&path).unwrap();
        let mut f = BufWriter::new(file);
        let mut sorted_nodes: Vec<_> = node_tri
            .iter()
            .filter(|(_, &v)| v > 0)
            .map(|(&k, &v)| (k, v))
            .collect();
        sorted_nodes.sort();
        for &(node_id, count) in &sorted_nodes {
            writeln!(f, "{} {}", node_id, count).unwrap();
        }
    }

    // Final edge list for external truss computation
    {
        let path = format!("{}/final_edges.txt", output_dir);
        let file = File::create(&path).unwrap();
        let mut f = BufWriter::new(file);
        for (u, v) in graph.sorted_edges() {
            writeln!(f, "{} {}", u, v).unwrap();
        }
    }

    eprintln!(
        "Pipeline complete: {} edges, {} triangles",
        graph.num_edges(),
        total_tri
    );
}
