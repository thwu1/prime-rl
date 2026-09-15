use std::collections::HashMap;

/// Type alias for variable environments.
pub type Env = HashMap<String, i64>;

/// An arithmetic expression AST.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Expr {
    /// Integer literal
    Lit(i64),
    /// Variable reference
    Var(String),
    /// Addition: a + b
    Add(Box<Expr>, Box<Expr>),
    /// Subtraction: a - b
    Sub(Box<Expr>, Box<Expr>),
    /// Multiplication: a * b
    Mul(Box<Expr>, Box<Expr>),
    /// Integer division: a / b (undefined when b == 0)
    Div(Box<Expr>, Box<Expr>),
    /// Unary negation: -a
    Neg(Box<Expr>),
    /// Conditional: if cond != 0 then expr1 else expr2
    If(Box<Expr>, Box<Expr>, Box<Expr>),
}

/// Evaluate an expression in the given environment.
///
/// Returns `None` if evaluation encounters division by zero or an unbound variable.
/// Uses wrapping arithmetic for add, sub, mul, neg to avoid overflow panics.
pub fn eval(expr: &Expr, env: &Env) -> Option<i64> {
    match expr {
        Expr::Lit(n) => Some(*n),
        Expr::Var(name) => env.get(name).copied(),
        Expr::Add(a, b) => {
            let x = eval(a, env)?;
            let y = eval(b, env)?;
            Some(x.wrapping_add(y))
        }
        Expr::Sub(a, b) => {
            let x = eval(a, env)?;
            let y = eval(b, env)?;
            Some(x.wrapping_sub(y))
        }
        Expr::Mul(a, b) => {
            let x = eval(a, env)?;
            let y = eval(b, env)?;
            Some(x.wrapping_mul(y))
        }
        Expr::Div(a, b) => {
            let x = eval(a, env)?;
            let y = eval(b, env)?;
            if y == 0 {
                None
            } else {
                Some(x.wrapping_div(y))
            }
        }
        Expr::Neg(a) => {
            let x = eval(a, env)?;
            Some(x.wrapping_neg())
        }
        Expr::If(cond, then_expr, else_expr) => {
            let c = eval(cond, env)?;
            if c != 0 {
                eval(then_expr, env)
            } else {
                eval(else_expr, env)
            }
        }
    }
}

/// Simplify an expression using algebraic identities and constant folding.
///
/// The simplified expression should evaluate identically to the original
/// for all environments. Subexpressions are simplified recursively before
/// applying rewrite rules.
pub fn simplify(expr: &Expr) -> Expr {
    match expr {
        Expr::Lit(_) | Expr::Var(_) => expr.clone(),

        Expr::Neg(a) => {
            let a = simplify(a);
            match a {
                Expr::Lit(n) => Expr::Lit(n.wrapping_neg()),
                Expr::Neg(inner) => *inner,
                _ => Expr::Neg(Box::new(a)),
            }
        }

        Expr::Add(a, b) => {
            let a = simplify(a);
            let b = simplify(b);
            match (&a, &b) {
                (Expr::Lit(x), Expr::Lit(y)) => Expr::Lit(x.wrapping_add(*y)),
                (Expr::Lit(0), _) => b,
                (_, Expr::Lit(0)) => a,
                _ => Expr::Add(Box::new(a), Box::new(b)),
            }
        }

        Expr::Sub(a, b) => {
            let a = simplify(a);
            let b = simplify(b);
            match (&a, &b) {
                (Expr::Lit(x), Expr::Lit(y)) => Expr::Lit(x.wrapping_sub(*y)),
                (_, Expr::Lit(0)) => a,
                // Simplify 0 - b
                (Expr::Lit(0), _) => b.clone(),
                _ => Expr::Sub(Box::new(a), Box::new(b)),
            }
        }

        Expr::Mul(a, b) => {
            let a = simplify(a);
            let b = simplify(b);
            match (&a, &b) {
                (Expr::Lit(x), Expr::Lit(y)) => Expr::Lit(x.wrapping_mul(*y)),
                (Expr::Lit(1), _) => b,
                // Simplify a * 1
                (_, Expr::Lit(1)) => b.clone(),
                _ => Expr::Mul(Box::new(a), Box::new(b)),
            }
        }

        Expr::Div(a, b) => {
            let a = simplify(a);
            let b = simplify(b);
            match (&a, &b) {
                (Expr::Lit(x), Expr::Lit(y)) if *y != 0 => Expr::Lit(x.wrapping_div(*y)),
                (_, Expr::Lit(1)) => a,
                // Simplify x / x
                _ if a == b => Expr::Lit(1),
                _ => Expr::Div(Box::new(a), Box::new(b)),
            }
        }

        Expr::If(cond, then_expr, else_expr) => {
            let cond = simplify(cond);
            match &cond {
                Expr::Lit(c) => {
                    if *c != 0 {
                        simplify(else_expr)
                    } else {
                        simplify(then_expr)
                    }
                }
                _ => Expr::If(
                    Box::new(cond),
                    Box::new(simplify(then_expr)),
                    Box::new(simplify(else_expr)),
                ),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eval_lit() {
        let env = Env::new();
        assert_eq!(eval(&Expr::Lit(42), &env), Some(42));
    }

    #[test]
    fn eval_var() {
        let mut env = Env::new();
        env.insert("x".into(), 10);
        assert_eq!(eval(&Expr::Var("x".into()), &env), Some(10));
        assert_eq!(eval(&Expr::Var("y".into()), &env), None);
    }

    #[test]
    fn eval_add() {
        let env = Env::new();
        let e = Expr::Add(Box::new(Expr::Lit(3)), Box::new(Expr::Lit(4)));
        assert_eq!(eval(&e, &env), Some(7));
    }

    #[test]
    fn eval_div_by_zero() {
        let env = Env::new();
        let e = Expr::Div(Box::new(Expr::Lit(10)), Box::new(Expr::Lit(0)));
        assert_eq!(eval(&e, &env), None);
    }

    #[test]
    fn eval_if_true() {
        let env = Env::new();
        let e = Expr::If(
            Box::new(Expr::Lit(1)),
            Box::new(Expr::Lit(10)),
            Box::new(Expr::Lit(20)),
        );
        assert_eq!(eval(&e, &env), Some(10));
    }

    #[test]
    fn eval_if_false() {
        let env = Env::new();
        let e = Expr::If(
            Box::new(Expr::Lit(0)),
            Box::new(Expr::Lit(10)),
            Box::new(Expr::Lit(20)),
        );
        assert_eq!(eval(&e, &env), Some(20));
    }

    #[test]
    fn simplify_const_fold_add() {
        assert_eq!(simplify(&Expr::Add(Box::new(Expr::Lit(3)), Box::new(Expr::Lit(4)))), Expr::Lit(7));
    }

    #[test]
    fn simplify_identity_add_zero() {
        let e = Expr::Add(Box::new(Expr::Lit(0)), Box::new(Expr::Var("x".into())));
        assert_eq!(simplify(&e), Expr::Var("x".into()));
    }

    #[test]
    fn simplify_double_neg() {
        let e = Expr::Neg(Box::new(Expr::Neg(Box::new(Expr::Var("x".into())))));
        assert_eq!(simplify(&e), Expr::Var("x".into()));
    }
}
