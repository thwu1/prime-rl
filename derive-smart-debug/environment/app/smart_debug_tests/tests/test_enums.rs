
use smart_debug::SmartDebug;

#[derive(SmartDebug)]
enum Shape {
    Circle { radius: f64 },
    Rectangle { width: f64, height: f64 },
    Point,
}

#[test]
fn test_struct_variant() {
    let s = Shape::Circle { radius: 5.0 };
    assert_eq!(format!("{:?}", s), "Circle { radius: 5.0 }");
}

#[test]
fn test_struct_variant_multi() {
    let s = Shape::Rectangle {
        width: 3.0,
        height: 4.0,
    };
    assert_eq!(
        format!("{:?}", s),
        "Rectangle { width: 3.0, height: 4.0 }"
    );
}

#[test]
fn test_unit_variant() {
    let s = Shape::Point;
    assert_eq!(format!("{:?}", s), "Point");
}

#[derive(SmartDebug)]
enum Value {
    Int(i64),
    Float(f64),
    Text(String),
}

#[test]
fn test_tuple_variant_int() {
    assert_eq!(format!("{:?}", Value::Int(42)), "Int(42)");
}

#[test]
fn test_tuple_variant_float() {
    assert_eq!(format!("{:?}", Value::Float(3.14)), "Float(3.14)");
}

#[test]
fn test_tuple_variant_text() {
    assert_eq!(
        format!("{:?}", Value::Text("hello".to_string())),
        "Text(\"hello\")"
    );
}

#[derive(SmartDebug)]
enum Mixed {
    Nothing,
    Single(bool),
    Named { x: i32, y: i32 },
}

#[test]
fn test_mixed_unit() {
    assert_eq!(format!("{:?}", Mixed::Nothing), "Nothing");
}

#[test]
fn test_mixed_tuple() {
    assert_eq!(format!("{:?}", Mixed::Single(true)), "Single(true)");
}

#[test]
fn test_mixed_named() {
    assert_eq!(
        format!("{:?}", Mixed::Named { x: 1, y: 2 }),
        "Named { x: 1, y: 2 }"
    );
}

#[derive(SmartDebug)]
enum Option2<T> {
    Some(T),
    None,
}

#[test]
fn test_generic_enum() {
    assert_eq!(format!("{:?}", Option2::Some(99)), "Some(99)");
    assert_eq!(format!("{:?}", Option2::<i32>::None), "None");
}
