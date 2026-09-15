
import subprocess
import os
import pytest


def run_cmd(args, cwd="/app", timeout=60, stdin_input=None):
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=stdin_input,
    )


@pytest.fixture(scope="session", autouse=True)
def compile_compiler():
    """Compile the MicroJava compiler and VM with javac."""
    result = run_cmd(["javac", "MJ/Compiler.java", "MJ/Run.java"])
    assert result.returncode == 0, (
        f"javac failed to compile the MicroJava compiler.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def compile_mj(name):
    """Compile a .mj file and return True if .obj was produced."""
    run_cmd(["java", "MJ.Compiler", f"{name}.mj"])
    return os.path.exists(f"/app/{name}.obj")


def run_mj(name):
    """Run a compiled .obj and return stdout."""
    result = run_cmd(["java", "MJ.Run", f"{name}.obj"], timeout=30)
    return result.stdout


class TestBooleanTest:
    """Tests for BooleanTest.mj — comprehensive boolean type features."""

    @classmethod
    def setup_class(cls):
        assert compile_mj("BooleanTest"), "BooleanTest.mj failed to compile"
        raw = run_mj("BooleanTest")
        # Split output; last line(s) are VM completion message
        cls.lines = raw.strip().split("\n")

    def test_basic_bool_assignment(self):
        """boolean p = a > b (true=1); boolean q = a < b (false=0)"""
        assert self.lines[0] == "10", f"Expected '10', got '{self.lines[0]}'"

    def test_compound_and_or(self):
        """&&: T&&T=1, F&&T=0; ||: T||F=1, F||F=0"""
        assert self.lines[1] == "1010", f"Expected '1010', got '{self.lines[1]}'"

    def test_bool_constants(self):
        """true prints 1, false prints 0"""
        assert self.lines[2] == "10", f"Expected '10', got '{self.lines[2]}'"

    def test_bool_in_while_loop(self):
        """while(boolVar) loop counting to 5"""
        assert self.lines[3] == "5", f"Expected '5', got '{self.lines[3]}'"

    def test_bool_method_return(self):
        """boolean isPositive(42)=true, isPositive(0)=false"""
        assert self.lines[4] == "10", f"Expected '10', got '{self.lines[4]}'"

    def test_print_bool_directly(self):
        """print(true)=1, print(false)=0"""
        assert self.lines[5] == "10", f"Expected '10', got '{self.lines[5]}'"

    def test_parenthesized_compound(self):
        """(a<b || b>c) && c>a with a=1,b=2,c=3 → true"""
        assert self.lines[6] == "1", f"Expected '1', got '{self.lines[6]}'"


class TestBoolMethodTest:
    """Tests for BoolMethodTest.mj — boolean parameters and return values."""

    @classmethod
    def setup_class(cls):
        assert compile_mj("BoolMethodTest"), "BoolMethodTest.mj failed to compile"
        raw = run_mj("BoolMethodTest")
        cls.lines = raw.strip().split("\n")

    def test_bool_method_operations(self):
        """negate(t)=0, negate(f)=1, both(t,t)=1, both(t,f)=0, either(f,f)=0, either(f,t)=1"""
        assert self.lines[0] == "011001", f"Expected '011001', got '{self.lines[0]}'"
