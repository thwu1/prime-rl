// Incremental Datalog evaluator with stratified negation support.
//
// Implements:
// - Parsing of Datalog rules, facts, and batched updates
// - Stratification based on negative dependency analysis
// - Per-stratum fixed-point evaluation with nested-loop joins
// - Negation filtering for body atoms prefixed with "not"
// - Full re-evaluation (DRed-equivalent) for incremental maintenance
//

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs;

type Value = i64;
type Tuple = Vec<Value>;

#[derive(Clone, Debug)]
struct Atom {
    predicate: String,
    args: Vec<String>,
    negated: bool,
}

#[derive(Clone, Debug)]
struct Rule {
    head: Atom,
    body: Vec<Atom>,
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

fn parse_atom(input: &str) -> Atom {
    let s = input.trim();
    let (s, negated) = if let Some(rest) = s.strip_prefix("not ") {
        (rest.trim(), true)
    } else {
        (s, false)
    };
    let paren_start = s.find('(').expect("malformed atom: no '('");
    let paren_end = s.rfind(')').expect("malformed atom: no ')'");
    let predicate = s[..paren_start].trim().to_string();
    let args_str = &s[paren_start + 1..paren_end];
    let args: Vec<String> = if args_str.trim().is_empty() {
        Vec::new()
    } else {
        args_str.split(',').map(|a| a.trim().to_string()).collect()
    };
    Atom {
        predicate,
        args,
        negated,
    }
}

fn parse_rules(filename: &str) -> Vec<Rule> {
    let content = fs::read_to_string(filename).expect("cannot read rules file");
    let mut rules = Vec::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('%') {
            continue;
        }
        let line = line.strip_suffix('.').unwrap_or(line);
        if !line.contains(":-") {
            continue;
        }
        let (head_str, body_str) = line.split_once(":-").unwrap();
        let head = parse_atom(head_str);

        // Split body on commas at depth 0 (respecting parentheses)
        let mut body = Vec::new();
        let mut depth: i32 = 0;
        let mut current = String::new();
        for ch in body_str.chars() {
            match ch {
                '(' => {
                    depth += 1;
                    current.push(ch);
                }
                ')' => {
                    depth -= 1;
                    current.push(ch);
                }
                ',' if depth == 0 => {
                    if !current.trim().is_empty() {
                        body.push(parse_atom(&current));
                    }
                    current.clear();
                }
                _ => {
                    current.push(ch);
                }
            }
        }
        if !current.trim().is_empty() {
            body.push(parse_atom(&current));
        }

        rules.push(Rule { head, body });
    }
    rules
}

fn parse_facts(filename: &str) -> HashMap<String, BTreeSet<Tuple>> {
    let content = fs::read_to_string(filename).expect("cannot read facts file");
    let mut facts: HashMap<String, BTreeSet<Tuple>> = HashMap::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('%') {
            continue;
        }
        let line = line.strip_suffix('.').unwrap_or(line);
        let atom = parse_atom(line);
        let tuple: Tuple = atom
            .args
            .iter()
            .map(|a| a.parse::<Value>().expect("non-integer fact value"))
            .collect();
        facts.entry(atom.predicate).or_default().insert(tuple);
    }
    facts
}

fn parse_updates(filename: &str) -> Vec<Vec<(char, String, Tuple)>> {
    let content = fs::read_to_string(filename).expect("cannot read updates file");
    let mut batches = Vec::new();
    let mut current: Vec<(char, String, Tuple)> = Vec::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('%') {
            continue;
        }
        if line == "---" {
            if !current.is_empty() {
                batches.push(current);
                current = Vec::new();
            }
            continue;
        }
        let op = line.chars().next().unwrap();
        let rest = &line[1..];
        let rest = rest.strip_suffix('.').unwrap_or(rest);
        let atom = parse_atom(rest);
        let tuple: Tuple = atom
            .args
            .iter()
            .map(|a| a.parse::<Value>().unwrap())
            .collect();
        current.push((op, atom.predicate, tuple));
    }
    if !current.is_empty() {
        batches.push(current);
    }
    batches
}

// ---------------------------------------------------------------------------
// Stratification
// ---------------------------------------------------------------------------

fn compute_strata(rules: &[Rule]) -> Vec<Vec<usize>> {
    // Collect all derived predicates (those appearing as rule heads)
    let derived_preds: BTreeSet<String> = rules.iter().map(|r| r.head.predicate.clone()).collect();
    let all_preds: Vec<String> = derived_preds.into_iter().collect();
    let pred_to_idx: HashMap<String, usize> = all_preds
        .iter()
        .enumerate()
        .map(|(i, p)| (p.clone(), i))
        .collect();
    let n = all_preds.len();

    if n == 0 {
        return vec![];
    }

    // Build dependency edges: predicate i depends on predicate j
    let mut deps: Vec<Vec<(usize, bool)>> = vec![Vec::new(); n];
    for rule in rules {
        if let Some(&head_idx) = pred_to_idx.get(&rule.head.predicate) {
            for atom in &rule.body {
                if let Some(&body_idx) = pred_to_idx.get(&atom.predicate) {
                    deps[head_idx].push((body_idx, atom.negated));
                }
            }
        }
    }

    // Iteratively assign strata: negative deps require higher stratum
    let mut stratum: Vec<usize> = vec![0; n];
    let mut changed = true;
    while changed {
        changed = false;
        for i in 0..n {
            for &(j, is_neg) in &deps[i] {
                let required = if is_neg {
                    stratum[j] + 1
                } else {
                    stratum[j]
                };
                if stratum[i] < required {
                    stratum[i] = required;
                    changed = true;
                }
            }
        }
    }

    // Group rule indices by their head predicate's stratum
    let max_stratum = stratum.iter().copied().max().unwrap_or(0);
    let mut strata: Vec<Vec<usize>> = vec![Vec::new(); max_stratum + 1];
    for (rule_idx, rule) in rules.iter().enumerate() {
        if let Some(&pidx) = pred_to_idx.get(&rule.head.predicate) {
            strata[stratum[pidx]].push(rule_idx);
        }
    }

    strata
}

// ---------------------------------------------------------------------------
// Rule evaluation
// ---------------------------------------------------------------------------

fn evaluate_rule(rule: &Rule, facts: &HashMap<String, BTreeSet<Tuple>>) -> BTreeSet<Tuple> {
    let empty = BTreeSet::new();

    // Separate positive and negative body atoms
    let positive_atoms: Vec<&Atom> = rule.body.iter().filter(|a| !a.negated).collect();
    let negative_atoms: Vec<&Atom> = rule.body.iter().filter(|a| a.negated).collect();

    // Build variable bindings from positive atoms via nested-loop join
    let mut bindings: Vec<HashMap<String, Value>> = vec![HashMap::new()];

    for atom in &positive_atoms {
        let relation = facts.get(&atom.predicate).unwrap_or(&empty);
        let mut next_bindings = Vec::new();
        for binding in &bindings {
            for tuple in relation.iter() {
                if tuple.len() != atom.args.len() {
                    continue;
                }
                let mut ext = binding.clone();
                let mut ok = true;
                for (arg, &val) in atom.args.iter().zip(tuple.iter()) {
                    if arg.starts_with(|c: char| c.is_ascii_uppercase()) {
                        // Variable
                        if let Some(&existing) = ext.get(arg) {
                            if existing != val {
                                ok = false;
                                break;
                            }
                        } else {
                            ext.insert(arg.clone(), val);
                        }
                    } else {
                        // Constant
                        let cval: Value = arg.parse().unwrap();
                        if cval != val {
                            ok = false;
                            break;
                        }
                    }
                }
                if ok {
                    next_bindings.push(ext);
                }
            }
        }
        bindings = next_bindings;
    }

    // Filter bindings by negative atoms
    bindings.retain(|binding| {
        for atom in &negative_atoms {
            let relation = facts.get(&atom.predicate).unwrap_or(&empty);
            let tuple: Tuple = atom
                .args
                .iter()
                .map(|arg| {
                    if arg.starts_with(|c: char| c.is_ascii_uppercase()) {
                        *binding.get(arg).unwrap()
                    } else {
                        arg.parse::<Value>().unwrap()
                    }
                })
                .collect();
            if relation.contains(&tuple) {
                return false;
            }
        }
        true
    });

    // Project bindings onto head arguments
    let mut result = BTreeSet::new();
    for binding in &bindings {
        let tuple: Tuple = rule
            .head
            .args
            .iter()
            .map(|arg| {
                if arg.starts_with(|c: char| c.is_ascii_uppercase()) {
                    *binding.get(arg).unwrap()
                } else {
                    arg.parse::<Value>().unwrap()
                }
            })
            .collect();
        result.insert(tuple);
    }

    result
}

// ---------------------------------------------------------------------------
// Fixed-point computation with stratification
// ---------------------------------------------------------------------------

fn compute_fixpoint(
    rules: &[Rule],
    base_facts: &HashMap<String, BTreeSet<Tuple>>,
) -> HashMap<String, BTreeSet<Tuple>> {
    let mut facts = base_facts.clone();
    let strata = compute_strata(rules);

    for stratum_rule_indices in &strata {
        if stratum_rule_indices.is_empty() {
            continue;
        }
        // Fixed-point iteration within this stratum
        loop {
            let mut changed = false;
            for &rule_idx in stratum_rule_indices {
                let rule = &rules[rule_idx];
                let derived = evaluate_rule(rule, &facts);
                let pred = &rule.head.predicate;
                let current = facts.entry(pred.clone()).or_default();
                for tuple in derived {
                    if current.insert(tuple) {
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }
    }

    facts
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    let args: Vec<String> = std::env::args().collect();

    let mut rules_file = String::new();
    let mut facts_file = String::new();
    let mut updates_file = String::new();
    let mut query = String::new();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--rules" => {
                rules_file = args[i + 1].clone();
                i += 2;
            }
            "--facts" => {
                facts_file = args[i + 1].clone();
                i += 2;
            }
            "--updates" => {
                updates_file = args[i + 1].clone();
                i += 2;
            }
            "--query" => {
                query = args[i + 1].clone();
                i += 2;
            }
            _ => {
                i += 1;
            }
        }
    }

    let rules = parse_rules(&rules_file);
    let mut base_facts = parse_facts(&facts_file);
    let updates = parse_updates(&updates_file);

    // Identify derived predicates (rule heads) for clearing on re-evaluation
    let head_preds: HashSet<String> = rules.iter().map(|r| r.head.predicate.clone()).collect();

    // Initial evaluation
    let all_facts = compute_fixpoint(&rules, &base_facts);
    let empty = BTreeSet::new();
    let tuples: Vec<Vec<Value>> = all_facts
        .get(&query)
        .unwrap_or(&empty)
        .iter()
        .cloned()
        .collect();
    println!(
        "{}",
        serde_json::json!({"batch": 0, "tuples": tuples})
    );

    // Process each update batch
    for (batch_num, batch) in updates.iter().enumerate() {
        // Apply base fact changes
        for (op, pred, tuple) in batch {
            match *op {
                '+' => {
                    base_facts.entry(pred.clone()).or_default().insert(tuple.clone());
                }
                '-' => {
                    if let Some(rel) = base_facts.get_mut(pred) {
                        rel.remove(tuple);
                    }
                }
                _ => {}
            }
        }

        // Re-evaluate: start from base facts only (clear all derived)
        let mut eval_base: HashMap<String, BTreeSet<Tuple>> = HashMap::new();
        for (pred, tuples) in &base_facts {
            if !head_preds.contains(pred) {
                eval_base.insert(pred.clone(), tuples.clone());
            }
        }

        let all_facts = compute_fixpoint(&rules, &eval_base);
        let tuples: Vec<Vec<Value>> = all_facts
            .get(&query)
            .unwrap_or(&empty)
            .iter()
            .cloned()
            .collect();
        println!(
            "{}",
            serde_json::json!({"batch": batch_num + 1, "tuples": tuples})
        );
    }
}
