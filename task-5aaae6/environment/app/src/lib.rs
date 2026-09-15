use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::exceptions::{PyKeyError, PyValueError};
use std::collections::{HashMap, BinaryHeap};
use std::sync::Mutex;
use std::cmp::Ordering;


#[derive(FromPyObject, Clone, Debug)]
struct EdgeConfig {
    weight: f64,
    directed: bool,
    label: Option<String>,
}

#[pyclass]
#[derive(Clone, Debug)]
struct Node {
    #[pyo3(get)]
    id: String,
    properties: HashMap<String, String>,
}

#[pymethods]
impl Node {
    #[new]
    fn new(id: String) -> Self {
        Node {
            id,
            properties: HashMap::new(),
        }
    }

    fn set_property(&mut self, key: String, value: String) {
        self.properties.insert(key, value);
    }

    fn get_property(&self, key: &str) -> PyResult<String> {
        self.properties
            .get(key)
            .cloned()
            .ok_or_else(|| PyKeyError::new_err(format!("Property '{}' not found", key)))
    }

    #[getter]
    fn property_count(&self) -> usize {
        self.properties.len()
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.id == other.id
    }

    fn __ne__(&self, other: &Self) -> bool {
        self.id != other.id
    }

    fn __repr__(&self) -> String {
        format!("Node(id='{}')", self.id)
    }

    fn __str__(&self) -> String {
        self.id.clone()
    }
}

#[pyclass]
#[derive(Clone, Debug)]
struct Edge {
    #[pyo3(get)]
    source: String,
    #[pyo3(get)]
    target: String,
    #[pyo3(get)]
    weight: f64,
    #[pyo3(get)]
    label: Option<String>,
}

#[pymethods]
impl Edge {
    fn __repr__(&self) -> String {
        format!(
            "Edge('{}' -> '{}', weight={})",
            self.source, self.target, self.weight
        )
    }
}

struct GraphInner {
    nodes: HashMap<String, Node>,
    edges: Vec<Edge>,
    adjacency: HashMap<String, Vec<(String, f64)>>,
}

impl GraphInner {
    fn new() -> Self {
        GraphInner {
            nodes: HashMap::new(),
            edges: Vec::new(),
            adjacency: HashMap::new(),
        }
    }
}

#[pyclass]
struct Graph {
    inner: Mutex<GraphInner>,
}

#[pymethods]
impl Graph {
    #[new]
    fn new() -> Self {
        Graph {
            inner: Mutex::new(GraphInner::new()),
        }
    }

    fn add_node(&self, id: String) -> PyResult<()> {
        let mut inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        if inner.nodes.contains_key(&id) {
            return Err(PyValueError::new_err(format!(
                "Node '{}' already exists",
                id
            )));
        }
        inner.nodes.insert(id.clone(), Node::new(id));
        Ok(())
    }

    fn add_node_with_props(
        &mut self,
        py: Python<'_>,
        id: String,
        props: HashMap<String, String>,
    ) -> PyResult<()> {
        py.allow_threads(|| {
            std::thread::sleep(std::time::Duration::from_millis(50));
        });
        let mut inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        if inner.nodes.contains_key(&id) {
            return Err(PyValueError::new_err(format!(
                "Node '{}' already exists",
                id
            )));
        }
        let mut node = Node::new(id.clone());
        node.properties = props;
        inner.nodes.insert(id, node);
        Ok(())
    }

    fn add_edge(
        &self,
        source: String,
        target: String,
        config: EdgeConfig,
    ) -> PyResult<()> {
        let mut inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        if !inner.nodes.contains_key(&source) {
            return Err(PyKeyError::new_err(format!(
                "Source node '{}' not found",
                source
            )));
        }
        if !inner.nodes.contains_key(&target) {
            return Err(PyKeyError::new_err(format!(
                "Target node '{}' not found",
                target
            )));
        }

        let edge = Edge {
            source: source.clone(),
            target: target.clone(),
            weight: config.weight,
            label: config.label.clone(),
        };
        inner.edges.push(edge);
        inner
            .adjacency
            .entry(source.clone())
            .or_default()
            .push((target.clone(), config.weight));
        if !config.directed {
            inner
                .adjacency
                .entry(target)
                .or_default()
                .push((source, config.weight));
        }
        Ok(())
    }

    fn node_count(&self) -> PyResult<usize> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner.nodes.len())
    }

    fn edge_count(&self) -> PyResult<usize> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner.edges.len())
    }

    fn has_node(&self, node_id: &str) -> PyResult<bool> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner.nodes.contains_key(node_id))
    }

    fn get_node(&self, node_id: &str) -> PyResult<Node> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        inner
            .nodes
            .get(node_id)
            .cloned()
            .ok_or_else(|| PyKeyError::new_err(format!("Node '{}' not found", node_id)))
    }

    fn get_neighbors(&self, node_id: &str) -> PyResult<Vec<(String, f64)>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner
            .adjacency
            .get(node_id)
            .cloned()
            .unwrap_or_default())
    }

    fn get_edges(&self) -> PyResult<Vec<Edge>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner.edges.clone())
    }

    fn node_ids(&self) -> PyResult<Vec<String>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(inner.nodes.keys().cloned().collect())
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        let dict = PyDict::new(py);

        let node_ids: Vec<String> = inner.nodes.keys().cloned().collect();
        dict.set_item("nodes", node_ids)?;

        let edge_tuples: Vec<(String, String, f64)> = inner
            .edges
            .iter()
            .map(|e| (e.source.clone(), e.target.clone(), e.weight))
            .collect();
        dict.set_item("edges", edge_tuples)?;

        Ok(dict)
    }

    fn shortest_path(
        &self,
        py: Python<'_>,
        source: &str,
        target: &str,
    ) -> PyResult<Option<(Vec<String>, f64)>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;

        if !inner.nodes.contains_key(source) {
            return Err(PyKeyError::new_err(format!(
                "Source node '{}' not found",
                source
            )));
        }
        if !inner.nodes.contains_key(target) {
            return Err(PyKeyError::new_err(format!(
                "Target node '{}' not found",
                target
            )));
        }

        let source_s = source.to_string();
        let target_s = target.to_string();

        Ok(py.allow_threads(|| {
            dijkstra(&inner.adjacency, &source_s, &target_s)
        }))
    }

    fn pagerank(
        &self,
        py: Python<'_>,
        damping: f64,
        iterations: usize,
    ) -> PyResult<HashMap<String, f64>> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        let adjacency = inner.adjacency.clone();
        let node_ids: Vec<String> = inner.nodes.keys().cloned().collect();
        drop(inner);

        Ok(py.allow_threads(|| {
            compute_pagerank(&node_ids, &adjacency, damping, iterations)
        }))
    }

    fn __len__(&self) -> PyResult<usize> {
        self.node_count()
    }

    fn __contains__(&self, node_id: &str) -> PyResult<bool> {
        self.has_node(node_id)
    }

    fn __repr__(&self) -> PyResult<String> {
        let inner = self.inner.lock().map_err(|e| {
            PyValueError::new_err(format!("Lock poisoned: {}", e))
        })?;
        Ok(format!(
            "Graph(nodes={}, edges={})",
            inner.nodes.len(),
            inner.edges.len()
        ))
    }
}

fn dijkstra(
    adjacency: &HashMap<String, Vec<(String, f64)>>,
    source: &str,
    target: &str,
) -> Option<(Vec<String>, f64)> {
    #[derive(PartialEq)]
    struct State {
        cost: f64,
        node: String,
    }
    impl Eq for State {}
    impl PartialOrd for State {
        fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
            Some(self.cmp(other))
        }
    }
    impl Ord for State {
        fn cmp(&self, other: &Self) -> Ordering {
            other
                .cost
                .partial_cmp(&self.cost)
                .unwrap_or(Ordering::Equal)
        }
    }

    let mut dist: HashMap<String, f64> = HashMap::new();
    let mut prev: HashMap<String, String> = HashMap::new();
    let mut heap = BinaryHeap::new();

    dist.insert(source.to_string(), 0.0);
    heap.push(State {
        cost: 0.0,
        node: source.to_string(),
    });

    while let Some(State { cost, node }) = heap.pop() {
        if node == target {
            let mut path = vec![target.to_string()];
            let mut current = target.to_string();
            while let Some(p) = prev.get(&current) {
                path.push(p.clone());
                current = p.clone();
            }
            path.reverse();
            return Some((path, cost));
        }

        if cost > *dist.get(&node).unwrap_or(&f64::INFINITY) {
            continue;
        }

        if let Some(neighbors) = adjacency.get(&node) {
            for (next, edge_weight) in neighbors {
                let next_cost = cost + edge_weight;
                if next_cost < *dist.get(next).unwrap_or(&f64::INFINITY) {
                    dist.insert(next.clone(), next_cost);
                    prev.insert(next.clone(), node.clone());
                    heap.push(State {
                        cost: next_cost,
                        node: next.clone(),
                    });
                }
            }
        }
    }

    None
}

fn compute_pagerank(
    node_ids: &[String],
    adjacency: &HashMap<String, Vec<(String, f64)>>,
    damping: f64,
    iterations: usize,
) -> HashMap<String, f64> {
    let n = node_ids.len() as f64;
    let mut ranks: HashMap<String, f64> =
        node_ids.iter().map(|id| (id.clone(), 1.0 / n)).collect();

    for _ in 0..iterations {
        let mut new_ranks: HashMap<String, f64> = node_ids
            .iter()
            .map(|id| (id.clone(), (1.0 - damping) / n))
            .collect();

        for (node, neighbors) in adjacency {
            if let Some(&rank) = ranks.get(node) {
                let share = rank / neighbors.len() as f64;
                for (target, _) in neighbors {
                    if let Some(r) = new_ranks.get_mut(target) {
                        *r += damping * share;
                    }
                }
            }
        }

        ranks = new_ranks;
    }

    ranks
}

#[pymodule]
fn graphdb(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Node>()?;
    m.add_class::<Edge>()?;
    m.add_class::<Graph>()?;
    Ok(())
}
