mod ffi;

use std::collections::BTreeMap;

#[derive(Clone)]
pub struct SortedSet {
    members: BTreeMap<String, f64>,
}

impl SortedSet {
    pub fn new() -> Self {
        SortedSet {
            members: BTreeMap::new(),
        }
    }

    /// Add or update a member. Returns true if newly added, false if updated.
    pub fn add(&mut self, member: &str, score: f64) -> bool {
        self.members.insert(member.to_string(), score).is_none()
    }

    /// Remove a member. Returns true if it existed.
    pub fn remove(&mut self, member: &str) -> bool {
        self.members.remove(member).is_some()
    }

    /// Get the score of a member.
    pub fn score(&self, member: &str) -> Option<f64> {
        self.members.get(member).copied()
    }

    /// Number of members.
    pub fn card(&self) -> usize {
        self.members.len()
    }

    /// Get entries sorted by (score ascending, member name ascending).
    pub fn sorted_entries(&self) -> Vec<(&str, f64)> {
        let mut entries: Vec<_> = self
            .members
            .iter()
            .map(|(k, &v)| (k.as_str(), v))
            .collect();
        entries.sort_by(|a, b| {
            a.1.partial_cmp(&b.1)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.0.cmp(b.0))
        });
        entries
    }

    /// Get 0-based rank of a member in score-ascending order.
    pub fn rank(&self, member: &str) -> Option<usize> {
        let entries = self.sorted_entries();
        entries.iter().position(|(k, _)| *k == member)
    }

    /// Get all entries with min <= score <= max, in ascending score order.
    pub fn range_by_score(&self, min: f64, max: f64) -> Vec<(String, f64)> {
        let entries = self.sorted_entries();
        entries
            .into_iter()
            .filter(|(_, score)| *score >= min && *score <= max)
            .map(|(k, v)| (k.to_string(), v))
            .collect()
    }

    /// Get entries at rank positions [start, stop] (inclusive on both ends).
    pub fn range_by_rank(&self, start: usize, stop: usize) -> Vec<(String, f64)> {
        let entries = self.sorted_entries();
        if start >= entries.len() {
            return vec![];
        }
        let end = std::cmp::min(stop + 1, entries.len());
        entries[start..end]
            .iter()
            .map(|(k, v)| (k.to_string(), *v))
            .collect()
    }
}
