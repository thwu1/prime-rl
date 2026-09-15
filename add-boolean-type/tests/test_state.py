
import subprocess
import os
import re
import pytest

COMPILER_DIR = "/app/Compiler"


def compile_and_run(source_code, test_name="test", stdin_input=None):
    """Compile a MicroJava program and run it on the VM.
    Returns (output, error_info). output is None if compilation failed."""
    src_file = f"/tmp/{test_name}.mj"
    obj_file = f"/tmp/{test_name}.obj"

    # Clean up from previous runs
    for f in [src_file, obj_file]:
        if os.path.exists(f):
            os.remove(f)

    with open(src_file, "w") as f:
        f.write(source_code)

    # Compile
    comp = subprocess.run(
        ["java", "-cp", COMPILER_DIR, "MJ.Compiler", src_file],
        capture_output=True, text=True, timeout=30,
    )

    if not os.path.exists(obj_file):
        return None, f"Compilation failed. stdout:\n{comp.stdout}\nstderr:\n{comp.stderr}"

    # Run on VM
    run = subprocess.run(
        ["java", "-cp", COMPILER_DIR, "MJ.Run", obj_file],
        capture_output=True, text=True, input=stdin_input, timeout=30,
    )
    output = run.stdout
    # Strip VM completion message
    output = re.sub(r"\nCompletion took \d+ ms$", "", output)
    return output, run.stderr


def test_basic_bool():
    """Basic boolean variable assignment with true/false and if conditions."""
    source = """\
program TestBasic
{
  void main()
    boolean b;
  {
    b = true;
    if (b) { print(1); print(chr(10)); }
    b = false;
    if (b) { print(2); print(chr(10)); }
    else { print(3); print(chr(10)); }
  }
}"""
    output, err = compile_and_run(source, "basic_bool")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "1\n3\n", f"Expected '1\\n3\\n', got {repr(output)}"


def test_bool_from_comparison():
    """Store comparison results with && and || in boolean variables."""
    source = """\
program TestComp
{
  void main()
    boolean b;
    int a, c;
  {
    a = 5;
    c = 10;
    b = a > 3 && c < 20;
    if (b) { print(1); print(chr(10)); }
    b = a > 10 || c > 5;
    if (b) { print(2); print(chr(10)); }
    b = a > 10 && c > 100;
    if (b) { print(3); print(chr(10)); }
    else { print(4); print(chr(10)); }
  }
}"""
    output, err = compile_and_run(source, "bool_comp")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "1\n2\n4\n", f"Expected '1\\n2\\n4\\n', got {repr(output)}"


def test_bool_while():
    """Boolean variable as while loop condition."""
    source = """\
program TestWhile
{
  void main()
    boolean running;
    int i;
  {
    i = 0;
    running = true;
    while (running) {
      print(i);
      print(chr(10));
      i++;
      if (i == 5) running = false;
    }
  }
}"""
    output, err = compile_and_run(source, "bool_while")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "0\n1\n2\n3\n4\n", f"Expected '0\\n1\\n2\\n3\\n4\\n', got {repr(output)}"


def test_print_bool():
    """Print boolean values (should output 1 or 0)."""
    source = """\
program TestPrint
{
  void main()
    boolean b;
    int x;
  {
    x = 5;
    b = x > 3;
    print(b);
    print(chr(10));
    b = x > 10;
    print(b);
    print(chr(10));
  }
}"""
    output, err = compile_and_run(source, "print_bool")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "1\n0\n", f"Expected '1\\n0\\n', got {repr(output)}"


def test_nested_bool():
    """Nested parenthesized boolean expressions."""
    source = """\
program TestNested
{
  void main()
    int a, b;
  {
    a = 1;
    b = 5;
    if ((a == 0 || a == 1) && b > 0) {
      print(1);
      print(chr(10));
    }
    if ((a == 0 || a == 1) && b < 0) {
      print(2);
      print(chr(10));
    } else {
      print(3);
      print(chr(10));
    }
  }
}"""
    output, err = compile_and_run(source, "nested_bool")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "1\n3\n", f"Expected '1\\n3\\n', got {repr(output)}"


def test_bool_method_return():
    """Methods with boolean return type."""
    source = """\
program TestMethod
{
  boolean isPositive(int x)
  {
    return x > 0;
  }

  void main()
    boolean b;
  {
    b = isPositive(5);
    if (b) { print(1); print(chr(10)); }
    b = isPositive(-3);
    if (b) { print(2); print(chr(10)); }
    else { print(3); print(chr(10)); }
  }
}"""
    output, err = compile_and_run(source, "bool_method")
    assert output is not None, f"Compilation failed: {err}"
    assert output == "1\n3\n", f"Expected '1\\n3\\n', got {repr(output)}"


def test_regression_existing():
    """Existing compound conditions and arithmetic must still work."""
    source = """\
program TestRegression
{
  void main()
    int i, sum;
  {
    i = 1;
    sum = 0;
    while (i <= 10) {
      if (i > 3 && i < 8) {
        sum = sum + i;
      }
      i++;
    }
    print(sum);
    print(chr(10));
  }
}"""
    output, err = compile_and_run(source, "regression")
    assert output is not None, f"Compilation failed: {err}"
    # 4 + 5 + 6 + 7 = 22
    assert output == "22\n", f"Expected '22\\n', got {repr(output)}"
