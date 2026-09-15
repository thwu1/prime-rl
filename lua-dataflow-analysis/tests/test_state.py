
import subprocess
import json
import os
import tempfile
import pytest

ANALYZER = "/app/lua_analyzer/analyze.lua"


def run_analyzer(lua_source: str) -> list:
    """Write lua_source to a temp file, run the analyzer, return parsed JSON warnings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False) as f:
        f.write(lua_source)
        f.flush()
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["lua5.4", ANALYZER, tmp_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 and not result.stdout.strip():
            raise RuntimeError(f"Analyzer failed: {result.stderr}")
        return json.loads(result.stdout.strip())
    finally:
        os.unlink(tmp_path)


class TestBasicUninitAccess:
    """Tests for accessing uninitialized variables in basic control flow."""

    def test_uninit_in_else_branch(self):
        """Variable is uninitialized in else branch of if-else."""
        warnings = run_analyzer("""
local a

if ... then
   a = 5
else
   a = get(a)
end

return a
""")
        assert len(warnings) == 1
        w = warnings[0]
        assert w["code"] == "321"
        assert w["name"] == "a"
        assert w["line"] == 7
        assert w["column"] == 12

    def test_mutating_uninit_variable(self):
        """Mutating (field-setting) an uninitialized variable."""
        warnings = run_analyzer("""
local a

if ... then
   a.k = 5
else
   a = get(5)
end

return a
""")
        assert len(warnings) == 1
        w = warnings[0]
        assert w["code"] == "341"
        assert w["name"] == "a"
        assert w["line"] == 5
        assert w["column"] == 4


class TestNoFalsePositives:
    """Ensure no warnings are emitted when code is correct."""

    def test_no_warning_initialized(self):
        """Fully initialized variable should produce no warning."""
        warnings = run_analyzer("""
local var = "foo"
return var
""")
        assert len(warnings) == 0

    def test_no_false_positive_in_loop(self):
        """Variable set in loop body before use on next iteration."""
        warnings = run_analyzer("""
local a

while not a do
   a = get()
end

return a
""")
        assert len(warnings) == 0

    def test_no_false_positive_unreachable_access(self):
        """Access after early return has no reaching values - not a 321."""
        warnings = run_analyzer("""
local var = "foo"
(...)(var)
do return end
(...)(var)
""")
        assert len(warnings) == 0

    def test_no_false_positive_upvalue_unreachable(self):
        """Upvalue access after early return has no reaching values."""
        warnings = run_analyzer("""
local var = "foo"
(...)(var)
do return end
(...)(function()
   return var
end)
""")
        assert len(warnings) == 0

    def test_both_branches_initialize(self):
        """Variable initialized in all branches."""
        warnings = run_analyzer("""
local a

if ... then
   a = 1
else
   a = 2
end

return a
""")
        assert len(warnings) == 0


class TestNestedFunctions:
    """Tests involving closures and upvalue semantics."""

    def test_uninit_in_nested_function(self):
        """Uninitialized access inside nested function."""
        warnings = run_analyzer("""
return function() return function(...)
local a

if ... then
   a = 5
else
   a = get(a)
end

return a
end end
""")
        assert len(warnings) == 1
        assert warnings[0]["code"] == "321"
        assert warnings[0]["name"] == "a"
        assert warnings[0]["line"] == 8
        assert warnings[0]["column"] == 12

    def test_uninit_in_deeply_nested_unreachable(self):
        """Uninitialized access in unreachable function still detected."""
        warnings = run_analyzer("""
return function()
   return function()
      do return end

      return function(x)
         local a

         if x then
            a = 1
            return a + 2
         else
            return a + 1
         end
      end
   end
end
""")
        assert len(warnings) == 1
        assert warnings[0]["code"] == "321"
        assert warnings[0]["name"] == "a"
        assert warnings[0]["line"] == 13
        assert warnings[0]["column"] == 20

    def test_no_false_positive_nested_unreachable_upvalue(self):
        """Upvalue access in nested func after early return."""
        warnings = run_analyzer("""
return function(...)
   local var = "foo"
   (...)(var)
   do return end
   (...)(function()
      return var
   end)
end
""")
        assert len(warnings) == 0


class TestBranching:
    """Tests for various branching patterns."""

    def test_if_elseif_else_partial_init(self):
        """Variable uninitialized in one branch."""
        warnings = run_analyzer("""
local a

if ... then
   a = 1
elseif ... then
   -- a not set here
else
   a = 3
end

return a
""")
        # No 321 warning: a has the empty initial value reaching print,
        # but it also has set values reaching. It's not "all empty".
        assert len(warnings) == 0

    def test_single_var_never_set_no_321(self):
        """Variable with exactly one empty value: reported as 'never set' (221), not 321."""
        warnings = run_analyzer("""
local a
return a
""")
        # Only one value (the empty initial one), so no 321 warning.
        assert len(warnings) == 0


class TestComplexControlFlow:
    """Tests for loops, gotos, and complex patterns."""

    def test_repeat_until_with_init(self):
        """Variable initialized in repeat loop before use."""
        warnings = run_analyzer("""
local a

repeat
   a = get()
until a

return a
""")
        assert len(warnings) == 0

    def test_for_loop_variable_initialized(self):
        """For loop variables are always initialized."""
        warnings = run_analyzer("""
for i = 1, 10 do
   print(i)
end
""")
        assert len(warnings) == 0

    def test_multiple_uninit_accesses(self):
        """Multiple uninitialized accesses reported correctly."""
        warnings = run_analyzer("""
local a
local b

if ... then
   a = 1
   b = 2
else
   a = get(a)
   b = get(b)
end

return a, b
""")
        assert len(warnings) == 2
        # Both should be 321
        assert all(w["code"] == "321" for w in warnings)
        names = {w["name"] for w in warnings}
        assert names == {"a", "b"}

    def test_while_loop_no_false_positive(self):
        """Variable set at top of while loop, used later."""
        warnings = run_analyzer("""
local result

while true do
   result = compute()
   if result then
      break
   end
end

return result
""")
        assert len(warnings) == 0


class TestEdgeCases:
    """Edge cases and tricky patterns."""

    def test_empty_source(self):
        """Empty source produces no warnings."""
        warnings = run_analyzer("")
        assert len(warnings) == 0

    def test_simple_assignment_no_warning(self):
        """Simple local assignment and use."""
        warnings = run_analyzer("""
local x = 42
print(x)
""")
        assert len(warnings) == 0

    def test_closure_upvalue_set(self):
        """Closure sets upvalue, main code reads it."""
        warnings = run_analyzer("""
local a

local function f()
   a = 5
end

f()
print(a)
""")
        # After resolve_locals, a's empty initial value and the closure assignment
        # both reach the print. Not all empty, so no 321.
        assert len(warnings) == 0

    def test_multiple_assignment_partial(self):
        """Multiple assignment where one var gets value from unpacking."""
        warnings = run_analyzer("""
local a, b = ...
print(a, b)
""")
        assert len(warnings) == 0

    def test_goto_label_flow(self):
        """Goto/label control flow - resolve_locals propagates all assignments."""
        warnings = run_analyzer("""
local a

goto skip
a = 1
::skip::

return a
""")
        # The resolve_locals stage propagates ALL assignments forward from their
        # position in the items array, regardless of whether the assignment itself
        # is reachable. The assignment `a = 1` is after the goto (unreachable code),
        # but its value still propagates forward from the label position onward.
        # So `return a` has two reaching values: the empty one AND the assignment.
        # Since not all reaching values are empty, no 321 warning is emitted.
        # (The unreachable assignment would be reported separately as unreachable
        # code, which is a different analysis stage not implemented here.)
        assert len(warnings) == 0
