
import csv
import os
import subprocess
import tempfile

import yaml


def load_ir(path):
    """Load a chiptool IR YAML and parse into blocks/fieldsets/enums dicts."""
    with open(path) as f:
        data = yaml.safe_load(f)

    blocks = {}
    fieldsets = {}
    enums = {}

    for key, val in data.items():
        if key.startswith("block/"):
            blocks[key[len("block/"):]] = val
        elif key.startswith("fieldset/"):
            fieldsets[key[len("fieldset/"):]] = val
        elif key.startswith("enum/"):
            enums[key[len("enum/"):]] = val

    return blocks, fieldsets, enums


def load_addrmap(path):
    """Load address map CSV."""
    entries = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)
    return entries


class TestTransformOutput:
    @classmethod
    def setup_class(cls):
        result = subprocess.run(
            ["python3", "/app/irtool.py"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"irtool.py failed: {result.stderr}"

        cls.blocks, cls.fieldsets, cls.enums = load_ir("/app/output.yaml")
        cls.addrmap = load_addrmap("/app/addrmap.csv")

    def test_block_count(self):
        """After transforms, there should be exactly 2 blocks."""
        assert len(self.blocks) == 2

    def test_block_names(self):
        """Blocks should be dma::Dma and dma::Channel after rename."""
        assert "dma::Dma" in self.blocks
        assert "dma::Channel" in self.blocks

    def test_channel_block_items(self):
        """Channel block should have 5 items: ctrl, xfer, src, dst, count."""
        ch_block = self.blocks["dma::Channel"]
        item_names = sorted([item["name"] for item in ch_block["items"]])
        assert item_names == sorted(["ctrl", "xfer", "src", "dst", "count"])

    def test_channel_ctrl_fieldset_ref(self):
        """Channel ctrl register should reference dma::regs::ChCtrl."""
        ch_block = self.blocks["dma::Channel"]
        ctrl_item = next(i for i in ch_block["items"] if i["name"] == "ctrl")
        assert ctrl_item["fieldset"] == "dma::regs::ChCtrl"

    def test_channel_byte_offsets(self):
        """Channel items should have correct relative byte offsets."""
        ch_block = self.blocks["dma::Channel"]
        offsets = {item["name"]: item["byte_offset"] for item in ch_block["items"]}
        assert offsets["ctrl"] == 0
        assert offsets["xfer"] == 4
        assert offsets["src"] == 8
        assert offsets["dst"] == 12
        assert offsets["count"] == 16

    def test_dma_ch_array(self):
        """dma::Dma should have 'ch' as an array of len 4, stride 32."""
        dma_block = self.blocks["dma::Dma"]
        ch_item = next(i for i in dma_block["items"] if i["name"] == "ch")
        assert ch_item["byte_offset"] == 0
        arr = ch_item["array"]
        assert arr["len"] == 4
        assert arr["stride"] == 32

    def test_dma_ch_block_ref(self):
        """ch item in dma::Dma should reference dma::Channel block."""
        dma_block = self.blocks["dma::Dma"]
        ch_item = next(i for i in dma_block["items"] if i["name"] == "ch")
        assert ch_item["block"] == "dma::Channel"

    def test_dma_timer_array(self):
        """dma::Dma should have 'timer' as an array of len 2, stride 4."""
        dma_block = self.blocks["dma::Dma"]
        timer_item = next(i for i in dma_block["items"] if i["name"] == "timer")
        assert timer_item["byte_offset"] == 272
        arr = timer_item["array"]
        assert arr["len"] == 2
        assert arr["stride"] == 4

    def test_fieldset_count(self):
        """After merges, should have exactly 5 fieldsets."""
        assert len(self.fieldsets) == 5

    def test_fieldset_names(self):
        """Fieldsets should be renamed to dma:: namespace."""
        expected = {
            "dma::regs::ChCtrl", "dma::regs::ChXfer", "dma::regs::ChCount",
            "dma::regs::Int", "dma::regs::Timer"
        }
        assert set(self.fieldsets.keys()) == expected

    def test_ctrl_fields(self):
        """ChCtrl fieldset should have all expected fields."""
        fs = self.fieldsets["dma::regs::ChCtrl"]
        field_names = {f["name"] for f in fs["fields"]}
        expected = {
            "en", "treq_sel", "data_size", "incr_read", "incr_write",
            "ring_size", "chain_to", "busy", "ahb_error"
        }
        assert field_names == expected

    def test_ctrl_enum_refs(self):
        """ChCtrl fields should reference renamed enums."""
        fs = self.fieldsets["dma::regs::ChCtrl"]
        treq = next(f for f in fs["fields"] if f["name"] == "treq_sel")
        assert treq["enum"] == "dma::vals::TreqSel"
        ds = next(f for f in fs["fields"] if f["name"] == "data_size")
        assert ds["enum"] == "dma::vals::DataSize"

    def test_int_field_arrays(self):
        """Int fieldset should have done and error as field arrays of len 4."""
        fs = self.fieldsets["dma::regs::Int"]
        field_names = {f["name"] for f in fs["fields"]}
        assert "done" in field_names
        assert "error" in field_names
        assert len(fs["fields"]) == 2

        done_field = next(f for f in fs["fields"] if f["name"] == "done")
        assert done_field["array"]["len"] == 4
        assert done_field["bit_offset"] == 0
        assert done_field["bit_size"] == 1

        error_field = next(f for f in fs["fields"] if f["name"] == "error")
        assert error_field["array"]["len"] == 4
        assert error_field["bit_offset"] == 4
        assert error_field["bit_size"] == 1

    def test_enum_count(self):
        """After merges, should have exactly 3 enums."""
        assert len(self.enums) == 3

    def test_enum_names(self):
        """Enums should be renamed to dma:: namespace."""
        expected = {"dma::vals::DataSize", "dma::vals::TreqSel", "dma::vals::BurstLen"}
        assert set(self.enums.keys()) == expected

    def test_data_size_enum(self):
        """DataSize enum should have correct variants."""
        e = self.enums["dma::vals::DataSize"]
        assert e["bit_size"] == 2
        variants = {v["name"]: v["value"] for v in e["variants"]}
        assert variants == {"BYTE": 0, "HALFWORD": 1, "WORD": 2}

    def test_treq_sel_variant_count(self):
        """TreqSel enum should have 11 variants."""
        e = self.enums["dma::vals::TreqSel"]
        assert len(e["variants"]) == 11

    def test_addrmap_exists(self):
        """Address map should exist and have entries."""
        assert len(self.addrmap) > 0

    def test_addrmap_ch0_ctrl(self):
        """ch[0].ctrl should be at address 0."""
        entry = next(
            (e for e in self.addrmap
             if "ch[0]" in e["path"] and e["path"].endswith(".ctrl")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 0

    def test_addrmap_ch1_ctrl(self):
        """ch[1].ctrl should be at address 32."""
        entry = next(
            (e for e in self.addrmap
             if "ch[1]" in e["path"] and e["path"].endswith(".ctrl")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 32

    def test_addrmap_ch2_src(self):
        """ch[2].src should be at address 64+8=72."""
        entry = next(
            (e for e in self.addrmap
             if "ch[2]" in e["path"] and e["path"].endswith(".src")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 72

    def test_addrmap_ch3_count(self):
        """ch[3].count should be at address 96+16=112."""
        entry = next(
            (e for e in self.addrmap
             if "ch[3]" in e["path"] and e["path"].endswith(".count")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 112

    def test_addrmap_ints(self):
        """ints should be at address 256 with Read access."""
        entry = next(
            (e for e in self.addrmap if e["path"].endswith(".ints")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 256
        assert entry["access"] == "Read"

    def test_addrmap_inte(self):
        """inte should be at address 260 with ReadWrite access."""
        entry = next(
            (e for e in self.addrmap if e["path"].endswith(".inte")),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 260
        assert entry["access"] == "ReadWrite"

    def test_addrmap_timer0(self):
        """timer[0] should be at address 272."""
        entry = next(
            (e for e in self.addrmap if "timer[0]" in e["path"]),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 272

    def test_addrmap_timer1(self):
        """timer[1] should be at address 276."""
        entry = next(
            (e for e in self.addrmap if "timer[1]" in e["path"]),
            None
        )
        assert entry is not None
        assert int(entry["address"]) == 276

    def test_addrmap_total_entries(self):
        """Should have exactly 26 register entries in the address map."""
        assert len(self.addrmap) == 26

    def test_no_old_xdma_refs(self):
        """No references to 'xdma' should remain after rename."""
        all_keys = (
            list(self.blocks.keys())
            + list(self.fieldsets.keys())
            + list(self.enums.keys())
        )
        for key in all_keys:
            assert "xdma" not in key, f"Found old xdma reference in key: {key}"

    def test_xfer_burst_len_ref(self):
        """ChXfer fieldset burst_len should reference dma::vals::BurstLen."""
        fs = self.fieldsets["dma::regs::ChXfer"]
        bl = next(f for f in fs["fields"] if f["name"] == "burst_len")
        assert bl["enum"] == "dma::vals::BurstLen"

    def test_dma_interrupt_regs_exist(self):
        """dma::Dma should have ints, inte, intf, intr as individual registers."""
        dma_block = self.blocks["dma::Dma"]
        item_names = {i["name"] for i in dma_block["items"]}
        for reg in ["ints", "inte", "intf", "intr"]:
            assert reg in item_names, f"Missing interrupt register {reg}"

    def test_dma_ints_access(self):
        """ints register in dma::Dma should have Read access."""
        dma_block = self.blocks["dma::Dma"]
        ints = next(i for i in dma_block["items"] if i["name"] == "ints")
        assert ints.get("access") == "Read"

    def test_channel_src_no_fieldset(self):
        """src register in Channel block should have no fieldset."""
        ch_block = self.blocks["dma::Channel"]
        src = next(i for i in ch_block["items"] if i["name"] == "src")
        assert "fieldset" not in src or src.get("fieldset") is None


class TestCHeader:
    """Tests for the generated C header file with register access macros."""

    @classmethod
    def setup_class(cls):
        if not os.path.exists("/app/registers.h"):
            result = subprocess.run(
                ["python3", "/app/irtool.py"],
                capture_output=True, text=True, cwd="/app"
            )
            assert result.returncode == 0, f"irtool.py failed: {result.stderr}"
        assert os.path.exists("/app/registers.h"), "registers.h was not generated"

    def _compile_c(self, code, description="C code"):
        """Helper: write C code to temp file and compile with gcc -fsyntax-only."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(code)
            tmp_path = f.name
        try:
            result = subprocess.run(
                ["gcc", "-fsyntax-only", "-std=c11", tmp_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"{description} compilation failed:\n{result.stderr}"
            )
        finally:
            os.unlink(tmp_path)

    def test_header_compiles(self):
        """Header must compile cleanly with gcc -fsyntax-only -std=c11."""
        result = subprocess.run(
            ["gcc", "-fsyntax-only", "-std=c11", "/app/registers.h"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"registers.h compilation failed:\n{result.stderr}"
        )

    def test_register_offsets(self):
        """Verify register offset macros have correct values."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_CH_OFFSET == 0x0, "");\n'
            '_Static_assert(DMA_CH_STRIDE == 0x20, "");\n'
            '_Static_assert(DMA_CH_LEN == 4, "");\n'
            '_Static_assert(DMA_CH_CTRL_OFFSET == 0x0, "");\n'
            '_Static_assert(DMA_CH_XFER_OFFSET == 0x4, "");\n'
            '_Static_assert(DMA_CH_SRC_OFFSET == 0x8, "");\n'
            '_Static_assert(DMA_CH_DST_OFFSET == 0xc, "");\n'
            '_Static_assert(DMA_CH_COUNT_OFFSET == 0x10, "");\n',
            "Channel register offsets"
        )

    def test_global_register_offsets(self):
        """Verify DMA-level register offset macros."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_INTS_OFFSET == 0x100, "");\n'
            '_Static_assert(DMA_INTE_OFFSET == 0x104, "");\n'
            '_Static_assert(DMA_INTF_OFFSET == 0x108, "");\n'
            '_Static_assert(DMA_INTR_OFFSET == 0x10c, "");\n'
            '_Static_assert(DMA_TIMER_OFFSET == 0x110, "");\n'
            '_Static_assert(DMA_TIMER_STRIDE == 0x4, "");\n'
            '_Static_assert(DMA_TIMER_LEN == 2, "");\n',
            "Global register offsets"
        )

    def test_ctrl_field_masks(self):
        """Verify ChCtrl field shift and positioned mask macros."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_CH_CTRL_EN_SHIFT == 0, "");\n'
            '_Static_assert(DMA_CH_CTRL_EN_MASK == 0x1, "");\n'
            '_Static_assert(DMA_CH_CTRL_TREQ_SEL_SHIFT == 1, "");\n'
            '_Static_assert(DMA_CH_CTRL_TREQ_SEL_MASK == 0x7e, "");\n'
            '_Static_assert(DMA_CH_CTRL_DATA_SIZE_SHIFT == 7, "");\n'
            '_Static_assert(DMA_CH_CTRL_DATA_SIZE_MASK == 0x180, "");\n'
            '_Static_assert(DMA_CH_CTRL_BUSY_SHIFT == 24, "");\n'
            '_Static_assert(DMA_CH_CTRL_BUSY_MASK == 0x1000000, "");\n'
            '_Static_assert(DMA_CH_CTRL_AHB_ERROR_SHIFT == 31, "");\n'
            '_Static_assert(DMA_CH_CTRL_AHB_ERROR_MASK == 0x80000000u, "");\n',
            "ChCtrl field masks"
        )

    def test_xfer_field_masks(self):
        """Verify ChXfer field shift and mask macros."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_CH_XFER_BURST_LEN_SHIFT == 0, "");\n'
            '_Static_assert(DMA_CH_XFER_BURST_LEN_MASK == 0xf, "");\n'
            '_Static_assert(DMA_CH_XFER_PRIORITY_SHIFT == 8, "");\n'
            '_Static_assert(DMA_CH_XFER_PRIORITY_MASK == 0x300, "");\n'
            '_Static_assert(DMA_CH_XFER_SNIFF_EN_SHIFT == 10, "");\n'
            '_Static_assert(DMA_CH_XFER_SNIFF_EN_MASK == 0x400, "");\n',
            "ChXfer field masks"
        )

    def test_timer_field_masks(self):
        """Verify Timer fieldset field macros."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_TIMER_X_SHIFT == 0, "");\n'
            '_Static_assert(DMA_TIMER_X_MASK == 0xffff, "");\n'
            '_Static_assert(DMA_TIMER_Y_SHIFT == 16, "");\n'
            '_Static_assert(DMA_TIMER_Y_MASK == 0xffff0000u, "");\n',
            "Timer field masks"
        )

    def test_int_field_arrays(self):
        """Verify interrupt fieldset field array macros."""
        self._compile_c(
            '#include "/app/registers.h"\n'
            '_Static_assert(DMA_INTS_DONE_SHIFT == 0, "");\n'
            '_Static_assert(DMA_INTS_DONE_MASK == 0x1, "");\n'
            '_Static_assert(DMA_INTS_DONE_LEN == 4, "");\n'
            '_Static_assert(DMA_INTS_DONE_STRIDE == 1, "");\n'
            '_Static_assert(DMA_INTS_ERROR_SHIFT == 4, "");\n'
            '_Static_assert(DMA_INTS_ERROR_MASK == 0x10, "");\n'
            '_Static_assert(DMA_INTS_ERROR_LEN == 4, "");\n'
            '_Static_assert(DMA_INTS_ERROR_STRIDE == 1, "");\n',
            "Int field array macros"
        )
