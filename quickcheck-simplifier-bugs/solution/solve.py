#!/usr/bin/env python3
"""
Solve the expr-simplify task:
1. Fix 4 bugs in src/lib.rs simplify function
2. Add Arbitrary + shrink implementation for Expr
3. Write property-based tests in tests/properties.rs
"""
import re

# --- Step 1: Read and fix lib.rs ---
with open("/app/src/lib.rs") as f:
    lib_content = f.read()

# Bug 1: Sub(Lit(0), _) returns b instead of Neg(b)
# Fix: (Expr::Lit(0), _) => b.clone()  ->  Expr::Neg(Box::new(b.clone()))
lib_content = lib_content.replace(
    '(Expr::Lit(0), _) => b.clone(),',
    '(Expr::Lit(0), _) => Expr::Neg(Box::new(b.clone())),',
    1  # only first occurrence (in Sub arm)
)

# Bug 2: Mul(_, Lit(1)) returns b instead of a
# Fix: (_, Expr::Lit(1)) => b.clone()  ->  a.clone()
# This one is trickier because we need to target the Mul arm specifically.
# The buggy line is "// Simplify a * 1" followed by "(_, Expr::Lit(1)) => b.clone(),"
lib_content = lib_content.replace(
    '// Simplify a * 1\n                (_, Expr::Lit(1)) => b.clone(),',
    '// Simplify a * 1\n                (_, Expr::Lit(1)) => a.clone(),',
)

# Bug 3: Div(a, b) when a == b -> Lit(1) without checking for zero
# Fix: remove the unsafe rule, or guard it for non-zero literals only
lib_content = lib_content.replace(
    '// Simplify x / x\n                _ if a == b => Expr::Lit(1),',
    '// Simplify x / x only when provably non-zero\n                (Expr::Lit(n), Expr::Lit(m)) if n == m && *n != 0 => Expr::Lit(1),',
)

# Bug 4: If branches are swapped
# Fix: when c != 0, return simplify(then_expr), not simplify(else_expr)
lib_content = lib_content.replace(
    '''if *c != 0 {
                        simplify(else_expr)
                    } else {
                        simplify(then_expr)
                    }''',
    '''if *c != 0 {
                        simplify(then_expr)
                    } else {
                        simplify(else_expr)
                    }''',
)

# --- Step 2: Add Arbitrary implementation ---
arbitrary_impl = '''

// --- QuickCheck Arbitrary implementation ---

use quickcheck::{Arbitrary, Gen};

impl Arbitrary for Expr {
    fn arbitrary(g: &mut Gen) -> Self {
        arbitrary_expr(g, g.size().min(5))
    }

    fn shrink(&self) -> Box<dyn Iterator<Item = Self>> {
        match self.clone() {
            Expr::Lit(n) => Box::new(n.shrink().map(Expr::Lit)),
            Expr::Var(_) => Box::new(std::iter::once(Expr::Lit(0))),
            Expr::Neg(a) => {
                let a = *a;
                Box::new(
                    std::iter::once(a.clone())
                        .chain(a.shrink().map(|s| Expr::Neg(Box::new(s)))),
                )
            }
            Expr::Add(a, b) => shrink_binop(*a, *b, |l, r| {
                Expr::Add(Box::new(l), Box::new(r))
            }),
            Expr::Sub(a, b) => shrink_binop(*a, *b, |l, r| {
                Expr::Sub(Box::new(l), Box::new(r))
            }),
            Expr::Mul(a, b) => shrink_binop(*a, *b, |l, r| {
                Expr::Mul(Box::new(l), Box::new(r))
            }),
            Expr::Div(a, b) => shrink_binop(*a, *b, |l, r| {
                Expr::Div(Box::new(l), Box::new(r))
            }),
            Expr::If(c, t, f) => {
                let (c, t, f) = (*c, *t, *f);
                let t1 = t.clone();
                let f1 = f.clone();
                let c1 = c.clone();
                let f2 = f.clone();
                let c2 = c.clone();
                let t2 = t.clone();
                Box::new(
                    vec![c.clone(), t.clone(), f.clone()]
                        .into_iter()
                        .chain(
                            c.shrink().map(move |s| {
                                Expr::If(
                                    Box::new(s),
                                    Box::new(t1.clone()),
                                    Box::new(f1.clone()),
                                )
                            }),
                        )
                        .chain(
                            t.shrink().map(move |s| {
                                Expr::If(
                                    Box::new(c1.clone()),
                                    Box::new(s),
                                    Box::new(f2.clone()),
                                )
                            }),
                        )
                        .chain(
                            f.shrink().map(move |s| {
                                Expr::If(
                                    Box::new(c2.clone()),
                                    Box::new(t2.clone()),
                                    Box::new(s),
                                )
                            }),
                        ),
                )
            }
        }
    }
}

fn shrink_binop(
    a: Expr,
    b: Expr,
    ctor: fn(Expr, Expr) -> Expr,
) -> Box<dyn Iterator<Item = Expr>> {
    let b1 = b.clone();
    let a1 = a.clone();
    Box::new(
        vec![a.clone(), b.clone()]
            .into_iter()
            .chain(a.shrink().map(move |s| ctor(s, b1.clone())))
            .chain(b.shrink().map(move |s| ctor(a1.clone(), s))),
    )
}

fn arbitrary_expr(g: &mut Gen, depth: usize) -> Expr {
    if depth == 0 {
        match *g.choose(&[0u8, 1]).unwrap() {
            0 => Expr::Lit(i8::arbitrary(g) as i64),
            _ => Expr::Var(
                g.choose(&["x", "y", "z"]).unwrap().to_string(),
            ),
        }
    } else {
        let d = depth - 1;
        match *g.choose(&[0u8, 1, 2, 3, 4, 5, 6, 7, 8, 9]).unwrap() {
            0 | 1 | 2 => Expr::Lit(i8::arbitrary(g) as i64),
            3 => Expr::Var(
                g.choose(&["x", "y", "z"]).unwrap().to_string(),
            ),
            4 => Expr::Add(
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
            ),
            5 => Expr::Sub(
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
            ),
            6 => Expr::Mul(
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
            ),
            7 => Expr::Div(
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
            ),
            8 => Expr::Neg(Box::new(arbitrary_expr(g, d))),
            9 => Expr::If(
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
                Box::new(arbitrary_expr(g, d)),
            ),
            _ => Expr::Lit(0),
        }
    }
}
'''

# Insert the Arbitrary impl before the #[cfg(test)] block
lib_content = lib_content.replace(
    '#[cfg(test)]',
    arbitrary_impl + '\n#[cfg(test)]',
    1,
)

with open("/app/src/lib.rs", "w") as f:
    f.write(lib_content)

# --- Step 3: Write property tests ---
properties_content = '''use expr_simplify::{eval, simplify, Env, Expr};
use quickcheck_macros::quickcheck;
use std::collections::HashMap;

#[quickcheck]
fn prop_simplify_preserves_eval(e: Expr, x: i8, y: i8, z: i8) -> bool {
    let mut env: Env = HashMap::new();
    env.insert("x".to_string(), x as i64);
    env.insert("y".to_string(), y as i64);
    env.insert("z".to_string(), z as i64);
    eval(&e, &env) == eval(&simplify(&e), &env)
}

#[quickcheck]
fn prop_simplify_idempotent(e: Expr) -> bool {
    simplify(&simplify(&e)) == simplify(&e)
}

#[quickcheck]
fn prop_double_simplify_same_eval(e: Expr, x: i8, y: i8, z: i8) -> bool {
    let mut env: Env = HashMap::new();
    env.insert("x".to_string(), x as i64);
    env.insert("y".to_string(), y as i64);
    env.insert("z".to_string(), z as i64);
    let s1 = simplify(&e);
    let s2 = simplify(&s1);
    eval(&s1, &env) == eval(&s2, &env)
}
'''

with open("/app/tests/properties.rs", "w") as f:
    f.write(properties_content)

print("Solution applied successfully.")
