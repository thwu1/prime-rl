
import subprocess
import os
import re

TIMEOUT = 180


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=TIMEOUT, **kwargs
    )


class TestGeneratorExecution:
    """Verify the generator runs and produces expected output files."""

    def test_generator_script_exists(self):
        assert os.path.isfile("/app/generate.py"), "generate.py not found at /app/"

    def test_generator_runs_successfully(self):
        result = run(["python3", "/app/generate.py"], cwd="/app")
        assert result.returncode == 0, f"Generator failed:\n{result.stderr}"

    def test_generated_cargo_toml_exists(self):
        assert os.path.isfile("/app/generated-pac/Cargo.toml"), (
            "Generated Cargo.toml not found"
        )

    def test_generated_lib_rs_exists(self):
        path = "/app/generated-pac/src/lib.rs"
        assert os.path.isfile(path), "Generated lib.rs not found"
        with open(path) as f:
            content = f.read()
        assert "#![no_std]" in content, "Generated crate must use #![no_std]"

    def test_generated_peripheral_modules_exist(self):
        for mod_name in ["gpioa", "gpiob", "spi1", "tim2"]:
            path = f"/app/generated-pac/src/{mod_name}.rs"
            assert os.path.isfile(path), f"Missing peripheral module: {mod_name}.rs"

    def test_generated_mmio_module_exists(self):
        assert os.path.isfile("/app/generated-pac/src/mmio.rs"), (
            "Missing mmio.rs module"
        )


class TestGeneratedCodeStructure:
    """Verify structural properties of the generated code."""

    def _extract_module_content(self, file_content, mod_name):
        """Extract the content of a pub mod block from a file."""
        start = file_content.find(f"pub mod {mod_name}")
        assert start != -1, f"{mod_name} module not found"
        # Find the next pub mod or pub struct at the top level
        rest = file_content[start + len(f"pub mod {mod_name}"):]
        next_boundary = len(file_content)
        for marker in ["\npub mod ", "\npub struct "]:
            idx = rest.find(marker)
            if idx != -1:
                pos = start + len(f"pub mod {mod_name}") + idx
                if pos < next_boundary:
                    next_boundary = pos
        return file_content[start:next_boundary]

    def test_read_only_register_has_no_writer(self):
        """GPIOA.IDR (read-only) must not have a W struct in its module."""
        with open("/app/generated-pac/src/gpioa.rs") as f:
            content = f.read()
        idr_content = self._extract_module_content(content, "idr")
        assert "pub struct R" in idr_content, "IDR should have reader type R"
        assert re.search(r"pub struct W\b", idr_content) is None, (
            "IDR (read-only) must NOT have writer type W"
        )

    def test_write_only_register_has_no_reader(self):
        """GPIOA.BSRR (write-only) must not have an R struct in its module."""
        with open("/app/generated-pac/src/gpioa.rs") as f:
            content = f.read()
        bsrr_content = self._extract_module_content(content, "bsrr")
        assert "pub struct W" in bsrr_content, "BSRR should have writer type W"
        assert re.search(r"pub struct R\b", bsrr_content) is None, (
            "BSRR (write-only) must NOT have reader type R"
        )

    def test_write_only_tim2_egr_has_no_reader(self):
        """TIM2.EGR (write-only) must not have an R struct."""
        with open("/app/generated-pac/src/tim2.rs") as f:
            content = f.read()
        egr_content = self._extract_module_content(content, "egr")
        assert "pub struct W" in egr_content, "EGR should have writer type W"
        assert re.search(r"pub struct R\b", egr_content) is None, (
            "EGR (write-only) must NOT have reader type R"
        )

    def test_spi1_sr_read_only_has_no_writer(self):
        """SPI1.SR (read-only) must not have a W struct."""
        with open("/app/generated-pac/src/spi1.rs") as f:
            content = f.read()
        sr_content = self._extract_module_content(content, "sr")
        assert "pub struct R" in sr_content, "SPI1.SR should have reader type R"
        assert re.search(r"pub struct W\b", sr_content) is None, (
            "SPI1.SR (read-only) must NOT have writer type W"
        )

    def test_gpiob_has_inherited_registers(self):
        """GPIOB (derived from GPIOA) must have inherited register modules."""
        with open("/app/generated-pac/src/gpiob.rs") as f:
            content = f.read()
        for reg_name in ["moder", "odr", "idr", "bsrr"]:
            assert f"pub mod {reg_name}" in content or f"pub {reg_name}:" in content, (
                f"GPIOB missing inherited register: {reg_name}"
            )

    def test_gpiob_has_additional_afrl(self):
        """GPIOB must have the AFRL register (not in GPIOA)."""
        with open("/app/generated-pac/src/gpiob.rs") as f:
            content = f.read()
        assert "afrl" in content.lower(), "GPIOB missing additional register AFRL"

    def test_gpioa_does_not_have_afrl(self):
        """GPIOA must NOT have the AFRL register (only GPIOB has it)."""
        with open("/app/generated-pac/src/gpioa.rs") as f:
            content = f.read()
        assert "afrl" not in content.lower(), (
            "GPIOA should NOT have AFRL (only GPIOB has it)"
        )

    def test_tim2_has_ccr_array_registers(self):
        """TIM2 must have CCR1-CCR4 register modules from dim expansion."""
        with open("/app/generated-pac/src/tim2.rs") as f:
            content = f.read()
        for i in range(1, 5):
            assert f"ccr{i}" in content.lower(), (
                f"TIM2 missing dim-expanded register CCR{i}"
            )


class TestCompilationAndIntegration:
    """Verify the generated PAC compiles and passes all integration tests."""

    def test_pac_compiles(self):
        result = run(["cargo", "build"], cwd="/app/generated-pac")
        assert result.returncode == 0, (
            f"PAC compilation failed:\n{result.stderr}"
        )

    def test_integration_tests_pass(self):
        result = subprocess.run(
            ["cargo", "test", "--", "--test-threads=1"],
            capture_output=True, text=True,
            cwd="/app/test_harness",
            timeout=240,
        )
        assert result.returncode == 0, (
            f"Integration tests failed:\n{result.stdout}\n{result.stderr}"
        )
