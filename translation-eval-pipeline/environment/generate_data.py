#!/usr/bin/env python3
"""Generate synthetic benchmark evaluation data for the translation benchmark analyzer task.

"""

import json
import os


DATA_DIR = "/data/benchmark"


def create_dir(path):
    os.makedirs(path, exist_ok=True)


def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def generate_manifest():
    manifest = {
        "benchmark_name": "RepoTransBench-Eval",
        "version": "1.0",
        "num_projects": 10,
        "projects": [
            {"id": "proj_01", "name": "string-utils"},
            {"id": "proj_02", "name": "math-engine"},
            {"id": "proj_03", "name": "graph-lib"},
            {"id": "proj_04", "name": "json-parser"},
            {"id": "proj_05", "name": "javalib-py"},
            {"id": "proj_06", "name": "converter-suite"},
            {"id": "proj_07", "name": "mathlib-go"},
            {"id": "proj_08", "name": "strlib-go"},
            {"id": "proj_09", "name": "mathlib-cpp"},
            {"id": "proj_10", "name": "cpp-mathlib-py"},
        ],
    }
    write_file(os.path.join(DATA_DIR, "manifest.json"), json.dumps(manifest, indent=2))


def generate_proj_01():
    """Python->Java, Maven build OK, JUnit 15/15 pass."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_01")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_01",
        "project_name": "string-utils",
        "source_language": "Python",
        "target_language": "Java",
        "build_tool": "maven",
        "test_framework": "junit",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = (
        "[INFO] Scanning for projects...\n"
        "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) ---\n"
        "[INFO] Compiling 8 source files to /app/target/classes\n"
        "[WARNING] /app/src/main/java/com/example/Utils.java:[15,23] unchecked cast\n"
        "[WARNING] /app/src/main/java/com/example/Utils.java:[42,17] redundant cast\n"
        "[INFO] BUILD SUCCESS\n"
        "[INFO] Total time: 2.341 s\n"
    )
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "[INFO] -------------------------------------------------------\n"
        "[INFO]  T E S T S\n"
        "[INFO] -------------------------------------------------------\n"
        "[INFO] Running com.example.StringUtilsTest\n"
        "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, "
        "Time elapsed: 0.234 s -- in com.example.StringUtilsTest\n"
        "[INFO] Running com.example.MathUtilsTest\n"
        "[INFO] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, "
        "Time elapsed: 0.156 s -- in com.example.MathUtilsTest\n"
        "[INFO] Running com.example.CollectionUtilsTest\n"
        "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, "
        "Time elapsed: 0.089 s -- in com.example.CollectionUtilsTest\n"
        "[INFO] \n"
        "[INFO] Results:\n"
        "[INFO] \n"
        "[INFO] Tests run: 15, Failures: 0, Errors: 0, Skipped: 0\n"
        "[INFO] \n"
        "[INFO] BUILD SUCCESS\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_02():
    """Python->Java, Maven build OK, JUnit 12/15 pass (2 fail, 1 error).

    Per-class counts differ from overall to expose first-vs-last match bugs.
    """
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_02")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_02",
        "project_name": "math-engine",
        "source_language": "Python",
        "target_language": "Java",
        "build_tool": "maven",
        "test_framework": "junit",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = (
        "[INFO] Scanning for projects...\n"
        "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) ---\n"
        "[INFO] Compiling 12 source files to /app/target/classes\n"
        "[INFO] BUILD SUCCESS\n"
        "[INFO] Total time: 3.127 s\n"
    )
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "[INFO] -------------------------------------------------------\n"
        "[INFO]  T E S T S\n"
        "[INFO] -------------------------------------------------------\n"
        "[INFO] Running com.example.ArithmeticTest\n"
        "[INFO] Tests run: 8, Failures: 0, Errors: 0, Skipped: 0, "
        "Time elapsed: 0.312 s -- in com.example.ArithmeticTest\n"
        "[INFO] Running com.example.AlgebraTest\n"
        "[INFO] Tests run: 4, Failures: 2, Errors: 1, Skipped: 0, "
        "Time elapsed: 0.198 s -- in com.example.AlgebraTest\n"
        "[ERROR] com.example.AlgebraTest.testQuadraticNegativeDiscriminant  "
        "Time elapsed: 0.011 s  <<< FAILURE!\n"
        "java.lang.AssertionError: expected complex roots but got NaN\n"
        "[ERROR] com.example.AlgebraTest.testLinearEquation  "
        "Time elapsed: 0.015 s  <<< FAILURE!\n"
        "java.lang.AssertionError: expected [1.0, 2.0] but got [2.0, 1.0]\n"
        "[ERROR] com.example.AlgebraTest.testMatrixInverse  "
        "Time elapsed: 0.008 s  <<< ERROR!\n"
        "java.lang.NullPointerException: matrix was null\n"
        "[INFO] Running com.example.StatisticsTest\n"
        "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, "
        "Time elapsed: 0.076 s -- in com.example.StatisticsTest\n"
        "[INFO] \n"
        "[INFO] Results:\n"
        "[INFO] \n"
        "[INFO] Tests run: 15, Failures: 2, Errors: 1, Skipped: 0\n"
        "[INFO] \n"
        "[INFO] BUILD FAILURE\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_03():
    """Python->Rust, cargo compile FAIL."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_03")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_03",
        "project_name": "graph-lib",
        "source_language": "Python",
        "target_language": "Rust",
        "build_tool": "cargo",
        "test_framework": "cargo_test",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = (
        "   Compiling graph-lib v0.1.0 (/app/target/graph-lib)\n"
        "error[E0308]: mismatched types\n"
        "  --> src/graph.rs:45:18\n"
        "   |\n"
        "45 |     let result: i32 = compute_path(graph);\n"
        "   |                 ---   ^^^^^^^^^^^^^^^^^^^ expected `i32`, found `Option<i32>`\n"
        "   |                 |\n"
        "   |                 expected due to this\n"
        "\n"
        "error[E0425]: cannot find value `visited` in this scope\n"
        "  --> src/traversal.rs:23:9\n"
        "   |\n"
        "23 |         visited.insert(node);\n"
        "   |         ^^^^^^^ not found in this scope\n"
        "\n"
        "error[E0599]: no method named `peek` found for struct `Vec<i32>` in the current scope\n"
        "  --> src/priority.rs:15:19\n"
        "   |\n"
        "15 |         self.heap.peek()\n"
        "   |                   ^^^^ method not found in `Vec<i32>`\n"
        "\n"
        "error: aborting due to 3 previous errors\n"
        "\n"
        "For more information about this error, try `rustc --explain E0308`.\n"
        "error: could not compile `graph-lib` (lib) due to 3 previous errors\n"
        "warning: build failed, waiting for other jobs to finish...\n"
    )
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = "error: could not compile `graph-lib` (lib test) due to 3 previous errors\n"
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_04():
    """Python->Rust, cargo compile OK, cargo test 8/12 pass, 2 ignored."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_04")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_04",
        "project_name": "json-parser",
        "source_language": "Python",
        "target_language": "Rust",
        "build_tool": "cargo",
        "test_framework": "cargo_test",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = (
        "   Compiling serde v1.0.193\n"
        "   Compiling json-parser v0.1.0 (/app/target/json-parser)\n"
        "warning: unused variable: `tmp`\n"
        "  --> src/parser.rs:67:13\n"
        "   |\n"
        "67 |         let tmp = self.peek();\n"
        "   |             ^^^ help: if this is intentional, prefix it with an underscore: `_tmp`\n"
        "   |\n"
        "   = note: `#[warn(unused_variables)]` on by default\n"
        "\n"
        "    Finished `test` profile [unoptimized + debuginfo] target(s) in 4.56s\n"
    )
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "     Running unittests src/lib.rs (target/debug/deps/json_parser-a1b2c3d4)\n"
        "\n"
        "running 14 tests\n"
        "test tokenizer::test_tokenize_string ... ok\n"
        "test tokenizer::test_tokenize_number ... ok\n"
        "test tokenizer::test_tokenize_boolean ... ok\n"
        "test tokenizer::test_tokenize_null ... ok\n"
        "test tokenizer::test_tokenize_array ... FAILED\n"
        "test parser::test_parse_object ... ok\n"
        "test parser::test_parse_array ... FAILED\n"
        "test parser::test_parse_nested ... ok\n"
        "test parser::test_parse_unicode ... FAILED\n"
        "test serializer::test_serialize_simple ... ok\n"
        "test serializer::test_serialize_nested ... FAILED\n"
        "test serializer::test_roundtrip ... ok\n"
        "test integration::test_large_file ... ignored\n"
        "test integration::test_streaming ... ignored\n"
        "\n"
        "failures:\n"
        "\n"
        "---- tokenizer::test_tokenize_array stdout ----\n"
        "thread 'tokenizer::test_tokenize_array' panicked at src/tokenizer.rs:89:9:\n"
        "assertion `left == right` failed\n"
        "  left: [Token::LBracket, Token::Number(1.0), Token::RBracket]\n"
        " right: [Token::LBracket, Token::Number(1.0), Token::Comma, "
        "Token::Number(2.0), Token::RBracket]\n"
        "\n"
        "---- parser::test_parse_array stdout ----\n"
        "thread 'parser::test_parse_array' panicked at src/parser.rs:134:9:\n"
        "assertion failed: matches!(result, Value::Array(_))\n"
        "\n"
        "---- parser::test_parse_unicode stdout ----\n"
        "thread 'parser::test_parse_unicode' panicked at src/parser.rs:156:9:\n"
        "assertion `left == right` failed\n"
        '  left: "hello"\n'
        ' right: "h\\u00e9llo"\n'
        "\n"
        "---- serializer::test_serialize_nested stdout ----\n"
        "thread 'serializer::test_serialize_nested' panicked at src/serializer.rs:78:9:\n"
        "assertion `left == right` failed\n"
        "\n"
        "failures:\n"
        "    tokenizer::test_tokenize_array\n"
        "    parser::test_parse_array\n"
        "    parser::test_parse_unicode\n"
        "    serializer::test_serialize_nested\n"
        "\n"
        "test result: FAILED. 8 passed; 4 failed; 2 ignored; "
        "0 measured; 0 filtered out; finished in 0.02s\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_05():
    """Java->Python, pytest 20/20 pass."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_05")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_05",
        "project_name": "javalib-py",
        "source_language": "Java",
        "target_language": "Python",
        "build_tool": "none",
        "test_framework": "pytest",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = "No compilation step required for Python target.\n"
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "============================= test session starts "
        "==============================\n"
        "platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.3.0\n"
        "rootdir: /app/target/javalib-py\n"
        "collected 20 items\n"
        "\n"
        "tests/test_string_ops.py::test_reverse PASSED\n"
        "tests/test_string_ops.py::test_concat PASSED\n"
        "tests/test_string_ops.py::test_split PASSED\n"
        "tests/test_string_ops.py::test_join PASSED\n"
        "tests/test_string_ops.py::test_strip PASSED\n"
        "tests/test_math_ops.py::test_add PASSED\n"
        "tests/test_math_ops.py::test_subtract PASSED\n"
        "tests/test_math_ops.py::test_multiply PASSED\n"
        "tests/test_math_ops.py::test_divide PASSED\n"
        "tests/test_math_ops.py::test_power PASSED\n"
        "tests/test_collection_ops.py::test_list_sort PASSED\n"
        "tests/test_collection_ops.py::test_dict_merge PASSED\n"
        "tests/test_collection_ops.py::test_set_union PASSED\n"
        "tests/test_collection_ops.py::test_deque_rotate PASSED\n"
        "tests/test_collection_ops.py::test_counter PASSED\n"
        "tests/test_parametrized.py::test_encode[ascii] PASSED\n"
        "tests/test_parametrized.py::test_encode[utf-8] PASSED\n"
        "tests/test_parametrized.py::test_encode[latin-1] PASSED\n"
        "tests/test_parametrized.py::test_decode[base64] PASSED\n"
        "tests/test_parametrized.py::test_decode[hex] PASSED\n"
        "\n"
        "============================== 20 passed in 0.34s "
        "==============================\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_06():
    """Java->Python, pytest 16/20 pass with ANSI color codes."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_06")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_06",
        "project_name": "converter-suite",
        "source_language": "Java",
        "target_language": "Python",
        "build_tool": "none",
        "test_framework": "pytest",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = "No compilation step required for Python target.\n"
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    G = "\x1b[32m"
    R = "\x1b[31m"
    B = "\x1b[1m"
    Z = "\x1b[0m"

    test_log = (
        f"{B}============================= test session starts "
        f"=============================={Z}\n"
        "platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.3.0\n"
        "rootdir: /app/target/converter-suite\n"
        "collected 20 items\n"
        "\n"
        f"tests/test_converter.py::test_int_to_str {G}PASSED{Z}\n"
        f"tests/test_converter.py::test_str_to_int {G}PASSED{Z}\n"
        f"tests/test_converter.py::test_float_to_str {G}PASSED{Z}\n"
        f"tests/test_converter.py::test_str_to_float {R}FAILED{Z}\n"
        f"tests/test_converter.py::test_bool_to_str {G}PASSED{Z}\n"
        f"tests/test_formatter.py::test_format_date {G}PASSED{Z}\n"
        f"tests/test_formatter.py::test_format_currency {R}FAILED{Z}\n"
        f"tests/test_formatter.py::test_format_percentage {G}PASSED{Z}\n"
        f"tests/test_formatter.py::test_format_phone {G}PASSED{Z}\n"
        f"tests/test_formatter.py::test_format_address {G}PASSED{Z}\n"
        f"tests/test_validator.py::test_validate_email {G}PASSED{Z}\n"
        f"tests/test_validator.py::test_validate_phone {R}FAILED{Z}\n"
        f"tests/test_validator.py::test_validate_url {G}PASSED{Z}\n"
        f"tests/test_validator.py::test_validate_ip {G}PASSED{Z}\n"
        f"tests/test_validator.py::test_validate_date {G}PASSED{Z}\n"
        f"tests/test_transform.py::test_camel_to_snake {G}PASSED{Z}\n"
        f"tests/test_transform.py::test_snake_to_camel {G}PASSED{Z}\n"
        f"tests/test_transform.py::test_title_case {R}FAILED{Z}\n"
        f"tests/test_transform.py::test_slug {G}PASSED{Z}\n"
        f"tests/test_transform.py::test_truncate {G}PASSED{Z}\n"
        "\n"
        f"{R}========================= 4 failed, 16 passed "
        f"========================={Z}\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_07():
    """Python->Go, go build OK, go test 10/10 pass."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_07")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_07",
        "project_name": "mathlib-go",
        "source_language": "Python",
        "target_language": "Go",
        "build_tool": "go",
        "test_framework": "go_test",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = "go build ./...\n"
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "=== RUN   TestAdd\n"
        "--- PASS: TestAdd (0.00s)\n"
        "=== RUN   TestSubtract\n"
        "--- PASS: TestSubtract (0.00s)\n"
        "=== RUN   TestMultiply\n"
        "--- PASS: TestMultiply (0.00s)\n"
        "=== RUN   TestDivide\n"
        "--- PASS: TestDivide (0.00s)\n"
        "=== RUN   TestModulo\n"
        "--- PASS: TestModulo (0.00s)\n"
        "=== RUN   TestPower\n"
        "--- PASS: TestPower (0.00s)\n"
        "=== RUN   TestAbs\n"
        "--- PASS: TestAbs (0.00s)\n"
        "=== RUN   TestMax\n"
        "--- PASS: TestMax (0.00s)\n"
        "=== RUN   TestMin\n"
        "--- PASS: TestMin (0.00s)\n"
        "=== RUN   TestClamp\n"
        "--- PASS: TestClamp (0.00s)\n"
        "PASS\n"
        "ok  \texample.com/mathlib\t0.003s\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_08():
    """Python->Go, go build OK, go test with subtests, 6/10 leaf pass."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_08")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_08",
        "project_name": "strlib-go",
        "source_language": "Python",
        "target_language": "Go",
        "build_tool": "go",
        "test_framework": "go_test",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = "go build ./...\n"
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "=== RUN   TestStringOps\n"
        "=== RUN   TestStringOps/Reverse\n"
        "--- PASS: TestStringOps/Reverse (0.00s)\n"
        "=== RUN   TestStringOps/Upper\n"
        "--- PASS: TestStringOps/Upper (0.00s)\n"
        "=== RUN   TestStringOps/Lower\n"
        "--- PASS: TestStringOps/Lower (0.00s)\n"
        "=== RUN   TestStringOps/Trim\n"
        "--- FAIL: TestStringOps/Trim (0.00s)\n"
        '    string_test.go:45: expected "hello", got " hello "\n'
        "--- FAIL: TestStringOps (0.00s)\n"
        "=== RUN   TestMathOps\n"
        "=== RUN   TestMathOps/Add\n"
        "--- PASS: TestMathOps/Add (0.00s)\n"
        "=== RUN   TestMathOps/Subtract\n"
        "--- PASS: TestMathOps/Subtract (0.00s)\n"
        "=== RUN   TestMathOps/Multiply\n"
        "--- FAIL: TestMathOps/Multiply (0.00s)\n"
        "    math_test.go:23: expected 6, got 5\n"
        "=== RUN   TestMathOps/Divide\n"
        "--- FAIL: TestMathOps/Divide (0.00s)\n"
        "    math_test.go:28: expected 2.5, got 2\n"
        "--- FAIL: TestMathOps (0.00s)\n"
        "=== RUN   TestSort\n"
        "--- PASS: TestSort (0.00s)\n"
        "=== RUN   TestSearch\n"
        "--- FAIL: TestSearch (0.00s)\n"
        "    search_test.go:15: expected index 3, got -1\n"
        "FAIL\n"
        "exit status 1\n"
        "FAIL\texample.com/strlib\t0.005s\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_09():
    """Python->C++, cmake build OK, Google Test 13/15 pass."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_09")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_09",
        "project_name": "mathlib-cpp",
        "source_language": "Python",
        "target_language": "C++",
        "build_tool": "cmake",
        "test_framework": "gtest",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = (
        "-- The CXX compiler identification is GNU 13.2.0\n"
        "-- Detecting CXX compiler ABI info\n"
        "-- Detecting CXX compiler ABI info - done\n"
        "-- Configuring done\n"
        "-- Generating done\n"
        "-- Build files have been written to: /app/target/build\n"
        "[  7%] Building CXX object CMakeFiles/mathlib.dir/src/math.cpp.o\n"
        "[ 15%] Building CXX object CMakeFiles/mathlib.dir/src/matrix.cpp.o\n"
        "[ 23%] Building CXX object CMakeFiles/mathlib.dir/src/statistics.cpp.o\n"
        "[ 30%] Linking CXX static library libmathlib.a\n"
        "[ 38%] Built target mathlib\n"
        "[ 46%] Building CXX object "
        "CMakeFiles/test_mathlib.dir/tests/test_main.cpp.o\n"
        "[ 53%] Linking CXX executable test_mathlib\n"
        "[ 61%] Built target test_mathlib\n"
    )
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "[==========] Running 15 tests from 3 test suites.\n"
        "[----------] Global test environment set-up.\n"
        "[----------] 5 tests from VectorMathTest\n"
        "[ RUN      ] VectorMathTest.DotProduct\n"
        "[       OK ] VectorMathTest.DotProduct (0 ms)\n"
        "[ RUN      ] VectorMathTest.CrossProduct\n"
        "[       OK ] VectorMathTest.CrossProduct (0 ms)\n"
        "[ RUN      ] VectorMathTest.Normalize\n"
        "[       OK ] VectorMathTest.Normalize (0 ms)\n"
        "[ RUN      ] VectorMathTest.Magnitude\n"
        "[       OK ] VectorMathTest.Magnitude (0 ms)\n"
        "[ RUN      ] VectorMathTest.AngleBetween\n"
        "[  FAILED  ] VectorMathTest.AngleBetween (0 ms)\n"
        "[----------] 5 tests from VectorMathTest (0 ms total)\n"
        "\n"
        "[----------] 6 tests from MatrixTest\n"
        "[ RUN      ] MatrixTest.Multiply\n"
        "[       OK ] MatrixTest.Multiply (0 ms)\n"
        "[ RUN      ] MatrixTest.Transpose\n"
        "[       OK ] MatrixTest.Transpose (0 ms)\n"
        "[ RUN      ] MatrixTest.Determinant\n"
        "[       OK ] MatrixTest.Determinant (0 ms)\n"
        "[ RUN      ] MatrixTest.Inverse\n"
        "[  FAILED  ] MatrixTest.Inverse (0 ms)\n"
        "[ RUN      ] MatrixTest.Identity\n"
        "[       OK ] MatrixTest.Identity (0 ms)\n"
        "[ RUN      ] MatrixTest.Trace\n"
        "[       OK ] MatrixTest.Trace (0 ms)\n"
        "[----------] 6 tests from MatrixTest (0 ms total)\n"
        "\n"
        "[----------] 4 tests from StatisticsTest\n"
        "[ RUN      ] StatisticsTest.Mean\n"
        "[       OK ] StatisticsTest.Mean (0 ms)\n"
        "[ RUN      ] StatisticsTest.Median\n"
        "[       OK ] StatisticsTest.Median (0 ms)\n"
        "[ RUN      ] StatisticsTest.StdDev\n"
        "[       OK ] StatisticsTest.StdDev (0 ms)\n"
        "[ RUN      ] StatisticsTest.Variance\n"
        "[       OK ] StatisticsTest.Variance (0 ms)\n"
        "[----------] 4 tests from StatisticsTest (0 ms total)\n"
        "\n"
        "[----------] Global test environment tear-down\n"
        "[==========] 15 tests from 3 test suites ran. (1 ms total)\n"
        "[  PASSED  ] 13 tests.\n"
        "[  FAILED  ] 2 tests, listed below:\n"
        "[  FAILED  ] VectorMathTest.AngleBetween\n"
        "[  FAILED  ] MatrixTest.Inverse\n"
        "\n"
        " 2 FAILED TESTS\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def generate_proj_10():
    """C++->Python, pytest with errors (not just failures), 15/18."""
    proj_dir = os.path.join(DATA_DIR, "projects", "proj_10")
    create_dir(proj_dir)

    meta = {
        "project_id": "proj_10",
        "project_name": "cpp-mathlib-py",
        "source_language": "C++",
        "target_language": "Python",
        "build_tool": "none",
        "test_framework": "pytest",
    }
    write_file(os.path.join(proj_dir, "meta.json"), json.dumps(meta, indent=2))

    build_log = "No compilation step required for Python target.\n"
    write_file(os.path.join(proj_dir, "build.log"), build_log)

    test_log = (
        "============================= test session starts "
        "==============================\n"
        "platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.3.0\n"
        "rootdir: /app/target/cpp-mathlib-py\n"
        "collected 18 items\n"
        "\n"
        "tests/test_vectors.py::test_dot_product PASSED\n"
        "tests/test_vectors.py::test_cross_product PASSED\n"
        "tests/test_vectors.py::test_normalize PASSED\n"
        "tests/test_vectors.py::test_magnitude PASSED\n"
        "tests/test_vectors.py::test_angle_between PASSED\n"
        "tests/test_vectors.py::test_projection PASSED\n"
        "tests/test_matrices.py::test_multiply PASSED\n"
        "tests/test_matrices.py::test_transpose PASSED\n"
        "tests/test_matrices.py::test_determinant PASSED\n"
        "tests/test_matrices.py::test_inverse PASSED\n"
        "tests/test_matrices.py::test_identity PASSED\n"
        "tests/test_matrices.py::test_eigenvalues ERROR\n"
        "tests/test_statistics.py::test_mean PASSED\n"
        "tests/test_statistics.py::test_median PASSED\n"
        "tests/test_statistics.py::test_std_dev PASSED\n"
        "tests/test_statistics.py::test_variance PASSED\n"
        "tests/test_statistics.py::test_correlation FAILED\n"
        "tests/test_statistics.py::test_regression FAILED\n"
        "\n"
        "=========================== short test summary info "
        "============================\n"
        "FAILED tests/test_statistics.py::test_correlation - "
        "AssertionError: values differ\n"
        "FAILED tests/test_statistics.py::test_regression - "
        "TypeError: unsupported operand\n"
        "ERROR tests/test_matrices.py::test_eigenvalues - "
        "ImportError: numpy not found\n"
        "======================= 2 failed, 15 passed, 1 error "
        "==========================\n"
    )
    write_file(os.path.join(proj_dir, "test.log"), test_log)


def main():
    create_dir(DATA_DIR)
    create_dir(os.path.join(DATA_DIR, "projects"))

    generate_manifest()
    generate_proj_01()
    generate_proj_02()
    generate_proj_03()
    generate_proj_04()
    generate_proj_05()
    generate_proj_06()
    generate_proj_07()
    generate_proj_08()
    generate_proj_09()
    generate_proj_10()

    # Verify all expected files were created
    manifest_path = os.path.join(DATA_DIR, "manifest.json")
    assert os.path.isfile(manifest_path), f"FAIL: {manifest_path} not created"
    with open(manifest_path) as f:
        m = json.load(f)
    for p in m["projects"]:
        pid = p["id"]
        pdir = os.path.join(DATA_DIR, "projects", pid)
        for fname in ("meta.json", "build.log", "test.log"):
            fpath = os.path.join(pdir, fname)
            assert os.path.isfile(fpath), f"FAIL: {fpath} not created"
            assert os.path.getsize(fpath) > 0, f"FAIL: {fpath} is empty"

    print(f"Generated benchmark data in {DATA_DIR}")
    print(f"  - manifest.json")
    print(f"  - 10 project directories with meta.json, build.log, test.log")
    print("All files verified successfully.")


if __name__ == "__main__":
    main()
