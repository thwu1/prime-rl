
"""
Tests for the TB-MCU32 PAC implementation.
Verifies register definitions, typestate GPIO, volatile access,
singleton pattern, and ARM cross-compilation.
"""

import subprocess
import os
import re
import xml.etree.ElementTree as ET
import pytest

APP_DIR = "/app"
SVD_FILE = "/app/tb-mcu.svd"
SRC_DIR = "/app/src"


# ============================================================
# Helpers
# ============================================================

def collect_rust_sources():
    """Collect all .rs files under /app/src/"""
    sources = {}
    for root, dirs, files in os.walk(SRC_DIR):
        for f in files:
            if f.endswith(".rs"):
                path = os.path.join(root, f)
                with open(path) as fh:
                    sources[path] = fh.read()
    return sources


def all_source_text():
    """Concatenated text of all Rust source files."""
    return "\n".join(collect_rust_sources().values())


def normalize_hex(addr):
    """Return a set of common hex representations of an integer address."""
    patterns = set()
    h = f"{addr:08x}"
    H = f"{addr:08X}"
    # plain
    patterns.add(f"0x{h}")
    patterns.add(f"0x{H}")
    # short (no leading zeros beyond minimum)
    patterns.add(f"0x{addr:x}")
    patterns.add(f"0x{addr:X}")
    # Rust underscore style  0x4800_0000
    if len(h) == 8:
        patterns.add(f"0x{h[:4]}_{h[4:]}")
        patterns.add(f"0x{H[:4]}_{H[4:]}")
    return patterns


def addr_in_source(addr, src):
    """Check whether addr appears in src in any common hex format."""
    for p in normalize_hex(addr):
        if p in src:
            return True
    return False


def parse_svd_peripherals():
    """Parse SVD and return {name: base_address} for every peripheral."""
    tree = ET.parse(SVD_FILE)
    root = tree.getroot()
    periphs = {}
    for p in root.findall(".//peripheral"):
        name = p.find("name").text
        base = p.find("baseAddress").text
        periphs[name] = int(base, 0)
    return periphs


# ============================================================
# 1. Compilation
# ============================================================

class TestCompilation:
    def test_compiles_for_arm(self):
        """PAC must compile for thumbv7m-none-eabi."""
        result = subprocess.run(
            ["cargo", "build", "--target", "thumbv7m-none-eabi"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, (
            f"Compilation for thumbv7m-none-eabi failed:\n{result.stderr[:3000]}"
        )

    def test_no_std(self):
        """Root lib.rs must declare #![no_std]."""
        lib_rs = open(os.path.join(SRC_DIR, "lib.rs")).read()
        assert "#![no_std]" in lib_rs, "Missing #![no_std] in lib.rs"


# ============================================================
# 2. Peripheral base addresses
# ============================================================

class TestPeripheralAddresses:
    def test_rcc_base(self):
        assert addr_in_source(0x40021000, all_source_text()), "RCC base 0x40021000 missing"

    def test_gpioa_base(self):
        assert addr_in_source(0x48000000, all_source_text()), "GPIOA base 0x48000000 missing"

    def test_gpiob_base(self):
        assert addr_in_source(0x48000400, all_source_text()), "GPIOB base 0x48000400 missing"

    def test_gpioc_base(self):
        assert addr_in_source(0x48000800, all_source_text()), "GPIOC base 0x48000800 missing"

    def test_usart1_base(self):
        assert addr_in_source(0x40013800, all_source_text()), "USART1 base 0x40013800 missing"

    def test_spi1_base(self):
        assert addr_in_source(0x40013000, all_source_text()), "SPI1 base 0x40013000 missing"

    def test_dma1_base(self):
        assert addr_in_source(0x40020000, all_source_text()), "DMA1 base 0x40020000 missing"

    def test_all_svd_peripherals_present(self):
        """Every peripheral in the SVD must have its base address in source."""
        src = all_source_text()
        missing = []
        for name, addr in parse_svd_peripherals().items():
            if not addr_in_source(addr, src):
                missing.append(f"{name} (0x{addr:08X})")
        assert not missing, f"Missing peripheral base addresses: {', '.join(missing)}"


# ============================================================
# 3. GPIO register offsets
# ============================================================

class TestGPIORegisterOffsets:
    """GPIO register offsets must appear in the source."""

    def _src(self):
        return all_source_text()

    def test_otyper_offset(self):
        assert "0x04" in self._src() or "0x4" in self._src()

    def test_ospeedr_offset(self):
        assert "0x08" in self._src() or "0x8" in self._src()

    def test_pupdr_offset(self):
        s = self._src()
        assert "0x0C" in s or "0x0c" in s or "0x0_c" in s.lower()

    def test_idr_offset(self):
        assert "0x10" in self._src()

    def test_odr_offset(self):
        assert "0x14" in self._src()

    def test_bsrr_offset(self):
        assert "0x18" in self._src()

    def test_afrl_offset(self):
        assert "0x20" in self._src()

    def test_afrh_offset(self):
        assert "0x24" in self._src()


# ============================================================
# 4. Volatile access
# ============================================================

class TestVolatileAccess:
    def test_volatile_read(self):
        assert "read_volatile" in all_source_text(), "No read_volatile found"

    def test_volatile_write(self):
        assert "write_volatile" in all_source_text(), "No write_volatile found"


# ============================================================
# 5. Typestate GPIO
# ============================================================

class TestTypestateGPIO:
    def test_input_type(self):
        assert re.search(r"\bInput\b", all_source_text()), "Missing Input type"

    def test_output_type(self):
        assert re.search(r"\bOutput\b", all_source_text()), "Missing Output type"

    def test_alternate_type(self):
        assert re.search(r"\bAlternate\b", all_source_text()), "Missing Alternate type"

    def test_phantom_data(self):
        assert "PhantomData" in all_source_text(), "PhantomData required for typestate"

    def test_mode_transitions(self):
        """Must have into_* transition methods."""
        assert re.search(r"fn\s+into_", all_source_text()), "No into_* transitions found"

    def test_set_high(self):
        assert re.search(r"fn\s+set_high", all_source_text()), "No set_high method"

    def test_set_low(self):
        assert re.search(r"fn\s+set_low", all_source_text()), "No set_low method"

    def test_is_high(self):
        assert re.search(r"fn\s+is_high", all_source_text()), "No is_high method"

    def test_is_low(self):
        assert re.search(r"fn\s+is_low", all_source_text()), "No is_low method"

    def test_output_methods_constrained(self):
        """set_high must live inside an impl block constrained to Output."""
        src = all_source_text()
        found = re.search(
            r"impl[^;]*?Output[\s\S]*?fn\s+set_high", src
        )
        assert found, "set_high not in Output-constrained impl"

    def test_input_methods_constrained(self):
        """is_high must live inside an impl block constrained to Input."""
        src = all_source_text()
        found = re.search(
            r"impl[^;]*?Input[\s\S]*?fn\s+is_high", src
        )
        assert found, "is_high not in Input-constrained impl"

    def test_sub_modes_input(self):
        src = all_source_text()
        for mode in ("Floating", "PullUp", "PullDown"):
            assert re.search(rf"\b{mode}\b", src), f"Missing input sub-mode: {mode}"

    def test_sub_modes_output(self):
        src = all_source_text()
        for mode in ("PushPull", "OpenDrain"):
            assert re.search(rf"\b{mode}\b", src), f"Missing output sub-mode: {mode}"


# ============================================================
# 6. Singleton pattern
# ============================================================

class TestSingletonPattern:
    def test_take_function(self):
        assert re.search(r"fn\s+take", all_source_text()), "Missing take() function"

    def test_atomic_guard(self):
        src = all_source_text()
        assert "AtomicBool" in src, "Missing AtomicBool for singleton guard"


# ============================================================
# 7. Bit manipulation correctness
# ============================================================

class TestBitManipulation:
    def test_moder_2bit_shift(self):
        """MODER uses 2-bit fields — source must multiply pin index by 2."""
        assert re.search(r"\*\s*2", all_source_text()), "No pin*2 shift for MODER"

    def test_bsrr_reset_offset(self):
        """BSRR reset bits are at +16 from set bits."""
        src = all_source_text()
        assert re.search(r"\+\s*16", src) or re.search(r"<<\s*16", src), (
            "No +16 offset for BSRR reset bits"
        )

    def test_two_bit_mask(self):
        """Must use 2-bit mask (0b11) for MODER field manipulation."""
        src = all_source_text()
        assert "0b11" in src or "0x3" in src or "0x03" in src, (
            "No 2-bit mask (0b11 / 0x3) found for MODER fields"
        )


# ============================================================
# 8. Non-GPIO peripheral register offsets
# ============================================================

class TestNonGPIOOffsets:
    """Spot-check offsets for USART1, SPI1, and DMA1."""

    def _src(self):
        return all_source_text()

    def test_usart1_isr_offset(self):
        """USART1 ISR at offset 0x1C."""
        assert "0x1C" in self._src() or "0x1c" in self._src()

    def test_usart1_rdr_offset(self):
        """USART1 RDR at offset 0x24."""
        assert "0x24" in self._src()

    def test_usart1_tdr_offset(self):
        """USART1 TDR at offset 0x28."""
        assert "0x28" in self._src()

    def test_dma1_ccr1_offset(self):
        """DMA1 CCR1 at offset 0x08."""
        assert "0x08" in self._src() or "0x8" in self._src()

    def test_spi1_dr_offset(self):
        """SPI1 DR at offset 0x0C."""
        s = self._src()
        assert "0x0C" in s or "0x0c" in s
