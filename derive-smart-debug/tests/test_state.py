import subprocess
import os
import textwrap
import shutil


HIDDEN_TEST_RUST = textwrap.dedent(r'''
    use smart_debug::SmartDebug;
    use std::marker::PhantomData;

    // --- Struct with lifetime parameter ---

    #[derive(SmartDebug)]
    struct Ref<'a> {
        data: &'a str,
        len: usize,
    }

    #[test]
    fn test_lifetime_struct() {
        let s = "hello";
        let r = Ref { data: s, len: 5 };
        let debug = format!("{:?}", r);
        assert!(debug.contains("Ref"));
        assert!(debug.contains("data: \"hello\""));
        assert!(debug.contains("len: 5"));
    }

    // --- Generic with nested type ---

    #[derive(SmartDebug)]
    struct Nested<T> {
        items: Vec<Option<T>>,
    }

    #[test]
    fn test_nested_generic() {
        let n = Nested { items: vec![Some(1), None, Some(3)] };
        let debug = format!("{:?}", n);
        assert!(debug.contains("Nested"));
        assert!(debug.contains("items: [Some(1), None, Some(3)]"));
    }

    // --- Enum with all variant types ---

    #[derive(SmartDebug)]
    enum Message {
        Quit,
        Move { x: i32, y: i32 },
        Write(String),
        Color(u8, u8, u8),
    }

    #[test]
    fn test_hidden_enum_quit() {
        assert_eq!(format!("{:?}", Message::Quit), "Quit");
    }

    #[test]
    fn test_hidden_enum_move() {
        assert_eq!(
            format!("{:?}", Message::Move { x: 1, y: 2 }),
            "Move { x: 1, y: 2 }"
        );
    }

    #[test]
    fn test_hidden_enum_write() {
        assert_eq!(
            format!("{:?}", Message::Write("hello".to_string())),
            "Write(\"hello\")"
        );
    }

    #[test]
    fn test_hidden_enum_color() {
        assert_eq!(
            format!("{:?}", Message::Color(255, 128, 0)),
            "Color(255, 128, 0)"
        );
    }

    // --- All fields skipped ---

    #[derive(SmartDebug)]
    struct AllSkipped {
        #[debug(skip)]
        a: i32,
        #[debug(skip)]
        b: String,
    }

    #[test]
    fn test_all_skipped() {
        let s = AllSkipped { a: 1, b: "hi".to_string() };
        assert_eq!(format!("{:?}", s), "AllSkipped");
    }

    // --- Multiple format attributes ---

    #[derive(SmartDebug)]
    struct Multi {
        #[debug(fmt = "{:#b}")]
        flags: u8,
        #[debug(fmt = "{:.2}")]
        ratio: f64,
        normal: i32,
    }

    #[test]
    fn test_multiple_fmt_hidden() {
        let m = Multi { flags: 0b1010, ratio: 3.14159, normal: 42 };
        let debug = format!("{:?}", m);
        assert!(debug.contains("flags: 0b1010"));
        assert!(debug.contains("ratio: 3.14"));
        assert!(debug.contains("normal: 42"));
    }

    // --- PhantomData with multiple type params ---

    struct OpaqueA;
    struct OpaqueB;

    #[derive(SmartDebug)]
    struct BiPhantom<A, B> {
        label: String,
        _a: PhantomData<A>,
        _b: PhantomData<B>,
    }

    #[test]
    fn test_double_phantom() {
        let bp: BiPhantom<OpaqueA, OpaqueB> = BiPhantom {
            label: "test".to_string(),
            _a: PhantomData,
            _b: PhantomData,
        };
        assert_eq!(format!("{:?}", bp), "BiPhantom { label: \"test\" }");
    }

    // --- Rename + skip combined on different fields ---

    #[derive(SmartDebug)]
    struct Config {
        #[debug(rename = "host_name")]
        host: String,
        port: u16,
        #[debug(skip)]
        token: String,
    }

    #[test]
    fn test_rename_and_skip() {
        let c = Config {
            host: "localhost".to_string(),
            port: 8080,
            token: "secret".to_string(),
        };
        assert_eq!(
            format!("{:?}", c),
            "Config { host_name: \"localhost\", port: 8080 }"
        );
    }
''')


def _find_cargo():
    """Locate cargo binary, checking common installation paths."""
    cargo = shutil.which("cargo")
    if cargo:
        return cargo
    for path in ["/usr/bin/cargo", "/root/.cargo/bin/cargo", "/usr/local/bin/cargo"]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "cargo"


CARGO = _find_cargo()


def test_cargo_build():
    """Verify that the smart_debug macro crate compiles."""
    result = subprocess.run(
        [CARGO, "build", "-p", "smart_debug"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    print("BUILD STDOUT:", result.stdout)
    print("BUILD STDERR:", result.stderr)
    assert result.returncode == 0, f"cargo build failed: {result.stderr}"


def test_visible_tests_pass():
    """Run the visible Rust integration tests."""
    result = subprocess.run(
        [CARGO, "test", "-p", "smart_debug_tests", "--", "--test-threads=1"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    print("VISIBLE STDOUT:", result.stdout)
    print("VISIBLE STDERR:", result.stderr)
    assert result.returncode == 0, f"Visible cargo tests failed: {result.stderr}"
    assert "test result: ok" in result.stdout, "Expected 'test result: ok' in output"


def test_hidden_tests_pass():
    """Inject hidden test file and run all tests."""
    hidden_path = "/app/smart_debug_tests/tests/test_hidden.rs"
    with open(hidden_path, "w") as f:
        f.write(HIDDEN_TEST_RUST)

    result = subprocess.run(
        [CARGO, "test", "-p", "smart_debug_tests", "--", "--test-threads=1"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    print("HIDDEN STDOUT:", result.stdout)
    print("HIDDEN STDERR:", result.stderr)
    assert result.returncode == 0, f"Hidden cargo tests failed: {result.stderr}"
    assert "test result: ok" in result.stdout, "Expected 'test result: ok' in output"
