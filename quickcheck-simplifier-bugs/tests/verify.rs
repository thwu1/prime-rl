
//! Verification tests for the expression simplifier.
//! These tests target specific bug sites in the simplify function.

use expr_simplify::{eval, simplify, Env, Expr};
use std::collections::HashMap;

fn env_with(bindings: &[(&str, i64)]) -> Env {
    let mut env = HashMap::new();
    for (k, v) in bindings {
        env.insert(k.to_string(), *v);
    }
    env
}

#[test]
fn verify_sub_zero_produces_negation() {
    // 0 - x must evaluate to -x, not x.
    // With x=5: eval(0 - x) = -5, so simplify must also eval to -5.
    let e = Expr::Sub(
        Box::new(Expr::Lit(0)),
        Box::new(Expr::Var("x".into())),
    );
    let env = env_with(&[("x", 5)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(-5));
    assert_eq!(
        original, simplified,
        "Sub(0, Var(x)) with x=5: original={:?}, simplified={:?}",
        original, simplified
    );
}

#[test]
fn verify_sub_zero_negative() {
    // Also test with a negative value: 0 - (-3) = 3
    let e = Expr::Sub(
        Box::new(Expr::Lit(0)),
        Box::new(Expr::Var("x".into())),
    );
    let env = env_with(&[("x", -3)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(3));
    assert_eq!(original, simplified);
}

#[test]
fn verify_div_self_handles_zero() {
    // x / x when x = 0 must be None (division by zero), not Some(1).
    let e = Expr::Div(
        Box::new(Expr::Var("x".into())),
        Box::new(Expr::Var("x".into())),
    );
    let env = env_with(&[("x", 0)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, None);
    assert_eq!(
        original, simplified,
        "Div(Var(x), Var(x)) with x=0: original={:?}, simplified={:?}",
        original, simplified
    );
}

#[test]
fn verify_div_self_nonzero() {
    // x / x when x != 0 should be 1 (this should still work after the fix).
    let e = Expr::Div(
        Box::new(Expr::Var("x".into())),
        Box::new(Expr::Var("x".into())),
    );
    let env = env_with(&[("x", 7)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(1));
    assert_eq!(original, simplified);
}

#[test]
fn verify_if_correct_branch() {
    // if 1 then 10 else 20 must evaluate to 10 (the then-branch), not 20.
    let e = Expr::If(
        Box::new(Expr::Lit(1)),
        Box::new(Expr::Lit(10)),
        Box::new(Expr::Lit(20)),
    );
    let env = Env::new();
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(10));
    assert_eq!(
        original, simplified,
        "If(1, 10, 20): original={:?}, simplified={:?}",
        original, simplified
    );
}

#[test]
fn verify_if_false_branch() {
    // if 0 then 10 else 20 must evaluate to 20 (the else-branch).
    let e = Expr::If(
        Box::new(Expr::Lit(0)),
        Box::new(Expr::Lit(10)),
        Box::new(Expr::Lit(20)),
    );
    let env = Env::new();
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(20));
    assert_eq!(original, simplified);
}

#[test]
fn verify_mul_identity_right() {
    // x * 1 must evaluate to x, not to 1.
    let e = Expr::Mul(
        Box::new(Expr::Var("x".into())),
        Box::new(Expr::Lit(1)),
    );
    let env = env_with(&[("x", 7)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(7));
    assert_eq!(
        original, simplified,
        "Mul(Var(x), 1) with x=7: original={:?}, simplified={:?}",
        original, simplified
    );
}

#[test]
fn verify_mul_identity_left() {
    // 1 * x must also evaluate to x (should be correct).
    let e = Expr::Mul(
        Box::new(Expr::Lit(1)),
        Box::new(Expr::Var("x".into())),
    );
    let env = env_with(&[("x", 7)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(7));
    assert_eq!(original, simplified);
}

#[test]
fn verify_simplify_complex_expression() {
    // (0 - x) + (y * 1) with x=3, y=5
    // Should eval to (-3) + 5 = 2
    let e = Expr::Add(
        Box::new(Expr::Sub(
            Box::new(Expr::Lit(0)),
            Box::new(Expr::Var("x".into())),
        )),
        Box::new(Expr::Mul(
            Box::new(Expr::Var("y".into())),
            Box::new(Expr::Lit(1)),
        )),
    );
    let env = env_with(&[("x", 3), ("y", 5)]);
    let original = eval(&e, &env);
    let simplified = eval(&simplify(&e), &env);
    assert_eq!(original, Some(2));
    assert_eq!(
        original, simplified,
        "Complex expr: original={:?}, simplified={:?}",
        original, simplified
    );
}

#[test]
fn verify_simplify_idempotent() {
    let exprs = vec![
        Expr::Sub(Box::new(Expr::Lit(0)), Box::new(Expr::Var("x".into()))),
        Expr::Mul(Box::new(Expr::Var("y".into())), Box::new(Expr::Lit(1))),
        Expr::If(
            Box::new(Expr::Lit(1)),
            Box::new(Expr::Var("x".into())),
            Box::new(Expr::Var("y".into())),
        ),
        Expr::If(
            Box::new(Expr::Lit(0)),
            Box::new(Expr::Lit(100)),
            Box::new(Expr::Lit(200)),
        ),
        Expr::Add(
            Box::new(Expr::Sub(
                Box::new(Expr::Lit(0)),
                Box::new(Expr::Var("x".into())),
            )),
            Box::new(Expr::Mul(
                Box::new(Expr::Var("y".into())),
                Box::new(Expr::Lit(1)),
            )),
        ),
    ];
    for e in &exprs {
        let s1 = simplify(e);
        let s2 = simplify(&s1);
        assert_eq!(s1, s2, "simplify is not idempotent for {:?}", e);
    }
}
