
use smart_debug::SmartDebug;

#[derive(SmartDebug)]
struct Point {
    x: f64,
    y: f64,
}

#[test]
fn test_basic_named_struct() {
    let p = Point { x: 1.0, y: 2.0 };
    assert_eq!(format!("{:?}", p), "Point { x: 1.0, y: 2.0 }");
}

#[derive(SmartDebug)]
struct Unit;

#[test]
fn test_unit_struct() {
    assert_eq!(format!("{:?}", Unit), "Unit");
}

#[derive(SmartDebug)]
struct Pair(i32, i32);

#[test]
fn test_tuple_struct() {
    let p = Pair(10, 20);
    assert_eq!(format!("{:?}", p), "Pair(10, 20)");
}

#[derive(SmartDebug)]
struct Single(String);

#[test]
fn test_single_tuple_struct() {
    let s = Single("hello".to_string());
    assert_eq!(format!("{:?}", s), "Single(\"hello\")");
}

#[derive(SmartDebug)]
struct ManyFields {
    a: i32,
    b: bool,
    c: String,
    d: f64,
}

#[test]
fn test_many_fields() {
    let m = ManyFields {
        a: 42,
        b: true,
        c: "test".to_string(),
        d: 3.14,
    };
    let debug = format!("{:?}", m);
    assert!(debug.starts_with("ManyFields { "));
    assert!(debug.contains("a: 42"));
    assert!(debug.contains("b: true"));
    assert!(debug.contains("c: \"test\""));
    assert!(debug.contains("d: 3.14"));
}
