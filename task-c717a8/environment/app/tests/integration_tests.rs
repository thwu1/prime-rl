
use expr_framework::array::*;
use expr_framework::datatype::DataType;
use expr_framework::expr::*;
use expr_framework::scalar::*;

// ---------------------------------------------------------------------------
// BinaryExpression direct usage tests
// ---------------------------------------------------------------------------

#[test]
fn test_cmp_le_i32_same_type() {
    let expr = BinaryExpression::<i32, i32, bool, _>::new(cmp_le::<i32, i32, i32>);
    let result = expr
        .eval_batch(
            &I32Array::from_slice(&[Some(1), Some(5), Some(3), None]).into(),
            &I32Array::from_slice(&[Some(2), Some(3), Some(3), Some(1)]).into(),
        )
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 1 < 2
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // 5 < 3
    assert_eq!(result.get(2), Some(ScalarRefImpl::Bool(false))); // 3 < 3 strict
    assert_eq!(result.get(3), None); // null propagation
}

#[test]
fn test_cmp_ge_cross_type_i16_f64() {
    let expr = BinaryExpression::<i16, f64, bool, _>::new(cmp_ge::<i16, f64, f64>);
    let result = expr
        .eval_batch(
            &I16Array::from_slice(&[Some(10), Some(2), None]).into(),
            &F64Array::from_slice(&[Some(5.0), Some(3.0), Some(1.0)]).into(),
        )
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 10 >= 5.0
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // 2 >= 3.0
    assert_eq!(result.get(2), None); // null propagation
}

#[test]
fn test_str_contains_direct() {
    let expr = BinaryExpression::<String, String, bool, _>::new(str_contains);
    let result = expr
        .eval_batch(
            &StringArray::from_slice(&[Some("hello world"), Some("foo"), None]).into(),
            &StringArray::from_slice(&[Some("world"), Some("baz"), Some("x")]).into(),
        )
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true)));
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false)));
    assert_eq!(result.get(2), None);
}

#[test]
fn test_cmp_eq_via_expression_trait() {
    let expr = BinaryExpression::<i32, i32, bool, _>::new(cmp_eq::<i32, i32, i32>);
    let i1 = I32Array::from_slice(&[Some(1), Some(2), Some(3)]).into();
    let i2 = I32Array::from_slice(&[Some(1), Some(5), Some(3)]).into();
    let result = expr.eval_expr(&[&i1, &i2]).unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 1 == 1
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // 2 == 5
    assert_eq!(result.get(2), Some(ScalarRefImpl::Bool(true))); // 3 == 3
}

// ---------------------------------------------------------------------------
// build_binary_expression tests
// ---------------------------------------------------------------------------

#[test]
fn test_build_cmp_le_i16_f64() {
    let expr = build_binary_expression(ExpressionFunc::CmpLe, DataType::SmallInt, DataType::Double);
    let result = expr
        .eval_expr(&[
            &I16Array::from_slice(&[Some(1), Some(100)]).into(),
            &F64Array::from_slice(&[Some(2.0), Some(50.0)]).into(),
        ])
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 1 < 2.0
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // 100 < 50.0
}

#[test]
fn test_build_cmp_ge_i32_i64() {
    let expr = build_binary_expression(ExpressionFunc::CmpGe, DataType::Integer, DataType::BigInt);
    let result = expr
        .eval_expr(&[
            &I32Array::from_slice(&[Some(10), Some(2)]).into(),
            &I64Array::from_slice(&[Some(5), Some(3)]).into(),
        ])
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 10 >= 5
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // 2 >= 3
}

#[test]
fn test_build_str_contains() {
    let expr = build_binary_expression(
        ExpressionFunc::StrContains,
        DataType::Varchar,
        DataType::Char { width: 10 },
    );
    let result = expr
        .eval_expr(&[
            &StringArray::from_slice(&[Some("000"), Some("111"), None]).into(),
            &StringArray::from_slice(&[Some("0"), Some("0"), None]).into(),
        ])
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true)));
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false)));
    assert_eq!(result.get(2), None);
}

#[test]
fn test_build_cmp_eq_ne() {
    let eq_expr =
        build_binary_expression(ExpressionFunc::CmpEq, DataType::Integer, DataType::Integer);
    let ne_expr =
        build_binary_expression(ExpressionFunc::CmpNe, DataType::Integer, DataType::Integer);
    let i1 = I32Array::from_slice(&[Some(1), Some(2)]).into();
    let i2 = I32Array::from_slice(&[Some(1), Some(3)]).into();

    let eq_result = eq_expr.eval_expr(&[&i1, &i2]).unwrap();
    assert_eq!(eq_result.get(0), Some(ScalarRefImpl::Bool(true))); // 1 == 1
    assert_eq!(eq_result.get(1), Some(ScalarRefImpl::Bool(false))); // 2 == 3

    let ne_result = ne_expr.eval_expr(&[&i1, &i2]).unwrap();
    assert_eq!(ne_result.get(0), Some(ScalarRefImpl::Bool(false))); // 1 != 1
    assert_eq!(ne_result.get(1), Some(ScalarRefImpl::Bool(true))); // 2 != 3
}

#[test]
fn test_build_cmp_i32_f32_cross() {
    // i32 vs f32 should cast to f64 for lossless comparison
    let expr = build_binary_expression(ExpressionFunc::CmpLe, DataType::Integer, DataType::Real);
    let result = expr
        .eval_expr(&[
            &I32Array::from_slice(&[Some(3)]).into(),
            &F32Array::from_slice(&[Some(3.5)]).into(),
        ])
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // 3 < 3.5
}

#[test]
fn test_build_cmp_le_varchar() {
    let expr =
        build_binary_expression(ExpressionFunc::CmpLe, DataType::Varchar, DataType::Varchar);
    let result = expr
        .eval_expr(&[
            &StringArray::from_slice(&[Some("apple"), Some("banana")]).into(),
            &StringArray::from_slice(&[Some("banana"), Some("apple")]).into(),
        ])
        .unwrap();
    assert_eq!(result.get(0), Some(ScalarRefImpl::Bool(true))); // "apple" < "banana"
    assert_eq!(result.get(1), Some(ScalarRefImpl::Bool(false))); // "banana" < "apple"
}

// ---------------------------------------------------------------------------
// Dynamic dispatch (Box<dyn Expression>) test
// ---------------------------------------------------------------------------

#[test]
fn test_dynamic_dispatch_vec() {
    let exprs: Vec<Box<dyn Expression>> = vec![
        build_binary_expression(ExpressionFunc::CmpLe, DataType::Integer, DataType::Integer),
        build_binary_expression(ExpressionFunc::CmpGe, DataType::SmallInt, DataType::BigInt),
        build_binary_expression(ExpressionFunc::StrContains, DataType::Varchar, DataType::Varchar),
    ];

    // CmpLe i32 vs i32
    let r1 = exprs[0]
        .eval_expr(&[
            &I32Array::from_slice(&[Some(1)]).into(),
            &I32Array::from_slice(&[Some(2)]).into(),
        ])
        .unwrap();
    assert_eq!(r1.get(0), Some(ScalarRefImpl::Bool(true)));

    // CmpGe i16 vs i64 (cast to i64)
    let r2 = exprs[1]
        .eval_expr(&[
            &I16Array::from_slice(&[Some(10)]).into(),
            &I64Array::from_slice(&[Some(5)]).into(),
        ])
        .unwrap();
    assert_eq!(r2.get(0), Some(ScalarRefImpl::Bool(true)));

    // StrContains
    let r3 = exprs[2]
        .eval_expr(&[
            &StringArray::from_slice(&[Some("abc")]).into(),
            &StringArray::from_slice(&[Some("b")]).into(),
        ])
        .unwrap();
    assert_eq!(r3.get(0), Some(ScalarRefImpl::Bool(true)));
}
