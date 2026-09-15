
use egg::*;
use serde::{Deserialize, Serialize};
use std::fs;

// ---------------------------------------------------------------------------
// Language definition
// ---------------------------------------------------------------------------

define_language! {
    enum Arith {
        Num(i64),
        "+" = Add([Id; 2]),
        "*" = Mul([Id; 2]),
        Symbol(Symbol),
    }
}

type ArithEGraph = EGraph<Arith, ConstantFold>;
type ArithRewrite = Rewrite<Arith, ConstantFold>;

// ---------------------------------------------------------------------------
// Constant-folding analysis
// ---------------------------------------------------------------------------

#[derive(Default, Debug, Clone)]
struct ConstantFold;

impl Analysis<Arith> for ConstantFold {
    type Data = Option<i64>;

    fn make(egraph: &ArithEGraph, enode: &Arith) -> Self::Data {
        let x = |i: &Id| egraph[*i].data;
        match enode {
            Arith::Num(n) => Some(*n),
            Arith::Add([a, b]) => Some(x(a)?.checked_add(x(b)?)?),
            Arith::Mul([a, b]) => Some(x(a)?.checked_mul(x(b)?)?),
            _ => None,
        }
    }

    fn merge(&mut self, to: &mut Self::Data, from: Self::Data) -> DidMerge {
        merge_option(to, from, |a, b| {
            assert_eq!(*a, b, "constant fold merge conflict");
            DidMerge(false, false)
        })
    }

    fn modify(egraph: &mut ArithEGraph, id: Id) {
        if let Some(c) = egraph[id].data {
            let added = egraph.add(Arith::Num(c));
            egraph.union(id, added);
        }
    }
}

// ---------------------------------------------------------------------------
// Rewrite rules
// ---------------------------------------------------------------------------

fn rules() -> Vec<ArithRewrite> {
    vec![
        rewrite!("comm-add";  "(+ ?a ?b)"        => "(+ ?b ?a)"),
        rewrite!("comm-mul";  "(* ?a ?b)"        => "(* ?b ?a)"),
        rewrite!("assoc-add"; "(+ (+ ?a ?b) ?c)" => "(+ ?a (+ ?b ?c))"),
        rewrite!("assoc-mul"; "(* (* ?a ?b) ?c)" => "(* ?a (* ?b ?c))"),
        rewrite!("add-0";     "(+ ?a 0)"         => "?a"),
        rewrite!("mul-1";     "(* ?a 1)"         => "?a"),
        rewrite!("mul-0";     "(* ?a 0)"         => "0"),
        rewrite!("dist";      "(* ?a (+ ?b ?c))" => "(+ (* ?a ?b) (* ?a ?c))"),
        rewrite!("factor";    "(+ (* ?a ?b) (* ?a ?c))" => "(* ?a (+ ?b ?c))"),
        rewrite!("double";    "(+ ?a ?a)"        => "(* 2 ?a)"),
    ]
}

// ---------------------------------------------------------------------------
// Cost function: AST node count
// ---------------------------------------------------------------------------

struct AstSize;

impl CostFunction<Arith> for AstSize {
    type Cost = usize;
    fn cost<C>(&mut self, enode: &Arith, mut costs: C) -> Self::Cost
    where
        C: FnMut(Id) -> Self::Cost,
    {
        enode.fold(1, |sum, id| sum + costs(id))
    }
}

// ---------------------------------------------------------------------------
// JSON I/O types
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct InputEntry {
    id: usize,
    expr: String,
    #[allow(dead_code)]
    max_cost: usize,
}

#[derive(Serialize)]
struct OutputEntry {
    id: usize,
    input: String,
    output: String,
    cost: usize,
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    let input_data =
        fs::read_to_string("/app/inputs.json").expect("Failed to read /app/inputs.json");
    let inputs: Vec<InputEntry> =
        serde_json::from_str(&input_data).expect("Failed to parse inputs.json");

    let rw = rules();
    let mut results: Vec<OutputEntry> = Vec::new();

    for entry in &inputs {
        let expr: RecExpr<Arith> = entry
            .expr
            .parse()
            .unwrap_or_else(|e| panic!("Bad S-expression '{}': {}", entry.expr, e));

        let runner = Runner::default()
            .with_expr(&expr)
            .with_iter_limit(30)
            .with_node_limit(100_000)
            .run(&rw);

        let root = runner.roots[0];
        let extractor = Extractor::new(&runner.egraph, AstSize);
        let (cost, best) = extractor.find_best(root);

        results.push(OutputEntry {
            id: entry.id,
            input: entry.expr.clone(),
            output: best.to_string(),
            cost,
        });
    }

    let out = serde_json::to_string_pretty(&results).expect("Failed to serialize results");
    fs::write("/app/results.json", &out).expect("Failed to write /app/results.json");

    eprintln!("Processed {} expressions:", results.len());
    for r in &results {
        eprintln!("  #{}: cost {} -> {}", r.id, r.cost, r.output);
    }
}
