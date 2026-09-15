
use smart_debug::SmartDebug;
use std::marker::PhantomData;

// --- Basic generic struct ---

#[derive(SmartDebug)]
struct Wrapper<T> {
    inner: T,
    label: String,
}

#[test]
fn test_generic_struct() {
    let w = Wrapper {
        inner: 42,
        label: "test".to_string(),
    };
    assert_eq!(
        format!("{:?}", w),
        "Wrapper { inner: 42, label: \"test\" }"
    );
}

// --- Skipped field removes Debug bound ---

struct NotDebug;

#[derive(SmartDebug)]
struct Container<T, U> {
    value: T,
    #[debug(skip)]
    _metadata: U,
}

#[test]
fn test_skip_removes_bound() {
    // U = NotDebug doesn't implement Debug, but the field is skipped
    // so this must compile and work.
    let c: Container<i32, NotDebug> = Container {
        value: 42,
        _metadata: NotDebug,
    };
    assert_eq!(format!("{:?}", c), "Container { value: 42 }");
}

// --- PhantomData auto-skip ---

#[derive(SmartDebug)]
struct Tagged<T> {
    id: u64,
    _phantom: PhantomData<T>,
}

#[test]
fn test_phantom_data_no_bound() {
    // T = NotDebug doesn't implement Debug, but PhantomData is auto-skipped
    // so this must compile and work.
    let t: Tagged<NotDebug> = Tagged {
        id: 123,
        _phantom: PhantomData,
    };
    assert_eq!(format!("{:?}", t), "Tagged { id: 123 }");
}

// --- Generic with Vec<T> ---

#[derive(SmartDebug)]
struct Collection<T> {
    items: Vec<T>,
    name: String,
}

#[test]
fn test_generic_vec() {
    let c = Collection {
        items: vec![1, 2, 3],
        name: "numbers".to_string(),
    };
    let debug = format!("{:?}", c);
    assert!(debug.contains("Collection"));
    assert!(debug.contains("items: [1, 2, 3]"));
    assert!(debug.contains("name: \"numbers\""));
}

// --- Multiple type params, one skipped ---

#[derive(SmartDebug)]
struct Mapping<K, V> {
    key: K,
    #[debug(skip)]
    _value: V,
}

#[test]
fn test_multiple_params_partial_skip() {
    let m: Mapping<String, NotDebug> = Mapping {
        key: "hello".to_string(),
        _value: NotDebug,
    };
    assert_eq!(format!("{:?}", m), "Mapping { key: \"hello\" }");
}
