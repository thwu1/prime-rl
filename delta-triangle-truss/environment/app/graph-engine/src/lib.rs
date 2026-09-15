use std::collections::{HashMap, HashSet};

/// Dynamic undirected graph backed by adjacency sets and an edge set.
pub struct Graph {
    adj: HashMap<u64, HashSet<u64>>,
    edges: HashSet<(u64, u64)>,
}

impl Graph {
    pub fn new() -> Self {
        Graph {
            adj: HashMap::new(),
            edges: HashSet::new(),
        }
    }

    /// Add an undirected edge between u and v. Returns true if the edge was new.
    pub fn add_edge(&mut self, u: u64, v: u64) -> bool {
        let (a, b) = Self::order(u, v);
        if self.edges.insert((a, b)) {
            self.adj.entry(a).or_default().insert(b);
            self.adj.entry(b).or_default().insert(a);
            true
        } else {
            false
        }
    }

    /// Remove an undirected edge between u and v. Returns true if the edge existed.
    pub fn remove_edge(&mut self, u: u64, v: u64) -> bool {
        let (a, b) = Self::order(u, v);
        if self.edges.remove(&(a, b)) {
            self.adj.entry(a).or_default().remove(&b);
            true
        } else {
            false
        }
    }

    /// Check if edge (u, v) exists.
    pub fn has_edge(&self, u: u64, v: u64) -> bool {
        let (a, b) = Self::order(u, v);
        self.edges.contains(&(a, b))
    }

    /// Return common neighbors of u and v.
    pub fn common_neighbors(&self, u: u64, v: u64) -> Vec<u64> {
        let empty = HashSet::new();
        let nu = self.adj.get(&u).unwrap_or(&empty);
        let nv = self.adj.get(&v).unwrap_or(&empty);
        nu.intersection(nv).copied().collect()
    }

    /// Return sorted list of all edges (u, v) with u < v.
    pub fn sorted_edges(&self) -> Vec<(u64, u64)> {
        let mut e: Vec<_> = self.edges.iter().copied().collect();
        e.sort();
        e
    }

    /// Return number of edges.
    pub fn num_edges(&self) -> usize {
        self.edges.len()
    }

    fn order(u: u64, v: u64) -> (u64, u64) {
        if u < v { (u, v) } else { (v, u) }
    }
}
