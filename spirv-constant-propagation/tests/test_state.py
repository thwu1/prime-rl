
import subprocess
import json
import os
import tempfile
import pytest

TOOL_PATH = "/app/analyze.py"
SHADERS_DIR = "/app/shaders/"
EXPECTED_PATH = "/app/expected.json"


def run_analyzer(shader_path):
    """Run the analyzer on a shader file and return parsed JSON results."""
    result = subprocess.run(
        ['python3', TOOL_PATH, shader_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Tool exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    output = result.stdout.strip()
    assert output, "Tool produced no output"
    return json.loads(output)


def run_analyzer_inline(spvasm_text):
    """Run the analyzer on inline SPIR-V assembly text."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.spvasm', delete=False) as f:
        f.write(spvasm_text)
        f.flush()
        tmpfile = f.name
    try:
        return run_analyzer(tmpfile)
    finally:
        os.unlink(tmpfile)


class TestArithFold:
    """Integer arithmetic constant folding from text assembly."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "arith_fold.spvasm"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 7, f"Expected 7, got {result['outparm']}"


class TestPhiMerge:
    """Phi node resolution from binary SPIR-V module."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "phi_merge.spv"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 4, f"Expected 4, got {result['outparm']}"


class TestDeadBranch:
    """Constant condition eliminates dead branch; value resolves via live path."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "dead_branch.spvasm"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 7, f"Expected 7, got {result['outparm']}"


class TestSwitchCase:
    """Switch with constant selector from binary module."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "switch_case.spv"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 19, f"Expected 19, got {result['outparm']}"


class TestNestedFlow:
    """Multi-level nested branches with cascading propagation."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "nested_flow.spvasm"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 13, f"Expected 13, got {result['outparm']}"


class TestLogicChain:
    """Logical negation chain from binary module."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "logic_chain.spv"))
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 20, f"Expected 20, got {result['outparm']}"


class TestMixedIO:
    """Multiple outputs: one constant-foldable, one runtime-dependent."""

    def test_result(self):
        result = run_analyzer(os.path.join(SHADERS_DIR, "mixed_io.spvasm"))
        assert "out_const" in result, f"Missing 'out_const' in result: {result}"
        assert "out_dyn" in result, f"Missing 'out_dyn' in result: {result}"
        assert result["out_const"] == 8, f"Expected 8, got {result['out_const']}"
        assert result["out_dyn"] is None, (
            f"Expected null for runtime-dependent value, got {result['out_dyn']}"
        )


class TestNovelMultiplication:
    """Novel shader: OpIMul constant folding (not in provided shaders)."""

    def test_imul_fold(self):
        spvasm = """\
               OpCapability Shader
          %1 = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint Fragment %main "main" %outparm
               OpExecutionMode %main OriginUpperLeft
               OpName %outparm "outparm"
               OpDecorate %outparm Location 0
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
        %int = OpTypeInt 32 1
%_ptr_Output_int = OpTypePointer Output %int
      %int_6 = OpConstant %int 6
      %int_7 = OpConstant %int 7
    %outparm = OpVariable %_ptr_Output_int Output
       %main = OpFunction %void None %3
          %5 = OpLabel
          %6 = OpIMul %int %int_6 %int_7
               OpStore %outparm %6
               OpReturn
               OpFunctionEnd
"""
        result = run_analyzer_inline(spvasm)
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 42, f"Expected 42, got {result['outparm']}"


class TestNovelLogicalBranch:
    """Novel shader: OpLogicalAnd determining branch (not in provided shaders)."""

    def test_and_false_branch(self):
        spvasm = """\
               OpCapability Shader
          %1 = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint Fragment %main "main" %outparm
               OpExecutionMode %main OriginUpperLeft
               OpName %outparm "outparm"
               OpDecorate %outparm Location 0
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
        %int = OpTypeInt 32 1
       %bool = OpTypeBool
%_ptr_Output_int = OpTypePointer Output %int
      %true = OpConstantTrue %bool
     %false = OpConstantFalse %bool
     %int_55 = OpConstant %int 55
     %int_99 = OpConstant %int 99
    %outparm = OpVariable %_ptr_Output_int Output
       %main = OpFunction %void None %3
         %10 = OpLabel
         %11 = OpLogicalAnd %bool %true %false
               OpSelectionMerge %merge None
               OpBranchConditional %11 %bb_t %bb_f
      %bb_t = OpLabel
               OpBranch %merge
      %bb_f = OpLabel
               OpBranch %merge
     %merge = OpLabel
         %12 = OpPhi %int %int_55 %bb_t %int_99 %bb_f
               OpStore %outparm %12
               OpReturn
               OpFunctionEnd
"""
        result = run_analyzer_inline(spvasm)
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 99, f"Expected 99, got {result['outparm']}"


class TestNovelArithCompare:
    """Novel shader: OpISub + OpSGreaterThan + Phi chain (not in provided shaders)."""

    def test_sub_compare_phi(self):
        spvasm = """\
               OpCapability Shader
          %1 = OpExtInstImport "GLSL.std.450"
               OpMemoryModel Logical GLSL450
               OpEntryPoint Fragment %main "main" %outparm
               OpExecutionMode %main OriginUpperLeft
               OpName %outparm "outparm"
               OpDecorate %outparm Location 0
       %void = OpTypeVoid
          %3 = OpTypeFunction %void
        %int = OpTypeInt 32 1
       %bool = OpTypeBool
%_ptr_Output_int = OpTypePointer Output %int
     %int_50 = OpConstant %int 50
     %int_15 = OpConstant %int 15
     %int_30 = OpConstant %int 30
    %int_999 = OpConstant %int 999
    %outparm = OpVariable %_ptr_Output_int Output
       %main = OpFunction %void None %3
         %10 = OpLabel
         %11 = OpISub %int %int_50 %int_15
         %12 = OpSGreaterThan %bool %11 %int_30
               OpSelectionMerge %merge None
               OpBranchConditional %12 %bb_t %bb_f
      %bb_t = OpLabel
               OpBranch %merge
      %bb_f = OpLabel
               OpBranch %merge
     %merge = OpLabel
         %13 = OpPhi %int %11 %bb_t %int_999 %bb_f
               OpStore %outparm %13
               OpReturn
               OpFunctionEnd
"""
        # ISub(50,15)=35, SGreaterThan(35,30)=true, true branch taken, Phi=35
        result = run_analyzer_inline(spvasm)
        assert "outparm" in result, f"Missing 'outparm' in result: {result}"
        assert result["outparm"] == 35, f"Expected 35, got {result['outparm']}"
