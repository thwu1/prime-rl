
use smart_debug::SmartDebug;

// --- Custom format string ---

#[derive(SmartDebug)]
struct Color {
    #[debug(fmt = "0x{:06x}")]
    rgb: u32,
    name: String,
}

#[test]
fn test_custom_format() {
    let c = Color {
        rgb: 0xFF5733,
        name: "orange".to_string(),
    };
    assert_eq!(
        format!("{:?}", c),
        "Color { rgb: 0xff5733, name: \"orange\" }"
    );
}

// --- Skip ---

#[derive(SmartDebug)]
struct Secret {
    username: String,
    #[debug(skip)]
    password: String,
}

#[test]
fn test_skip() {
    let s = Secret {
        username: "alice".to_string(),
        password: "hunter2".to_string(),
    };
    assert_eq!(format!("{:?}", s), "Secret { username: \"alice\" }");
}

// --- Rename ---

#[derive(SmartDebug)]
struct ApiResponse {
    #[debug(rename = "status_code")]
    code: u16,
    body: String,
}

#[test]
fn test_rename() {
    let r = ApiResponse {
        code: 200,
        body: "OK".to_string(),
    };
    assert_eq!(
        format!("{:?}", r),
        "ApiResponse { status_code: 200, body: \"OK\" }"
    );
}

// --- With ---

fn format_bytes(bytes: &Vec<u8>, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    write!(f, "[{} bytes]", bytes.len())
}

#[derive(SmartDebug)]
struct Packet {
    id: u32,
    #[debug(with = "format_bytes")]
    payload: Vec<u8>,
}

#[test]
fn test_with() {
    let p = Packet {
        id: 42,
        payload: vec![1, 2, 3, 4, 5],
    };
    assert_eq!(
        format!("{:?}", p),
        "Packet { id: 42, payload: [5 bytes] }"
    );
}

// --- Hex format ---

#[derive(SmartDebug)]
struct Register {
    #[debug(fmt = "0x{:04x}")]
    address: u16,
    #[debug(fmt = "0b{:08b}")]
    value: u8,
}

#[test]
fn test_multiple_fmt() {
    let r = Register {
        address: 0x1A2B,
        value: 0b11001010,
    };
    assert_eq!(
        format!("{:?}", r),
        "Register { address: 0x1a2b, value: 0b11001010 }"
    );
}
