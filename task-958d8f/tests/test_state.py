
import json
import re
import pytest


@pytest.fixture(scope="session")
def output():
    with open("/app/output.json") as f:
        return json.load(f)


# ── Sanitize: naming conventions ────────────────────────────────

class TestSanitizeNaming:
    def test_block_keys_are_path_snake_pascal(self, output):
        for key in output["blocks"]:
            segments = key.split("::")
            for seg in segments[:-1]:
                assert seg == seg.lower(), (
                    f"Block key non-terminal segment not snake: {key}"
                )
            assert segments[-1][0].isupper(), (
                f"Block key terminal segment not PascalCase: {key}"
            )

    def test_fieldset_keys_are_path_snake_pascal(self, output):
        for key in output["fieldsets"]:
            segments = key.split("::")
            for seg in segments[:-1]:
                assert seg == seg.lower(), (
                    f"Fieldset key non-terminal segment not snake: {key}"
                )
            assert segments[-1][0].isupper(), (
                f"Fieldset key terminal segment not PascalCase: {key}"
            )

    def test_enum_keys_are_path_snake_pascal(self, output):
        for key in output["enums"]:
            segments = key.split("::")
            for seg in segments[:-1]:
                assert seg == seg.lower(), (
                    f"Enum key non-terminal segment not snake: {key}"
                )
            assert segments[-1][0].isupper(), (
                f"Enum key terminal segment not PascalCase: {key}"
            )

    def test_block_item_names_are_snake(self, output):
        for bname, block in output["blocks"].items():
            for item in block["items"]:
                assert item["name"] == item["name"].lower(), (
                    f"Block '{bname}' item '{item['name']}' is not snake_case"
                )

    def test_field_names_are_snake(self, output):
        for fname, fs in output["fieldsets"].items():
            for field in fs["fields"]:
                assert field["name"] == field["name"].lower(), (
                    f"Fieldset '{fname}' field '{field['name']}' is not snake_case"
                )

    def test_variant_names_are_pascal(self, output):
        for ename, enum in output["enums"].items():
            for v in enum["variants"]:
                assert v["name"][0].isupper(), (
                    f"Enum '{ename}' variant '{v['name']}' not PascalCase"
                )
                assert "_" not in v["name"], (
                    f"Enum '{ename}' variant '{v['name']}' has underscore (not PascalCase)"
                )

    def test_keyword_escaped_field(self, output):
        """The CONFIG fieldset had a field 'TYPE' which after snake becomes
        'type' -- a Rust keyword that must be escaped to 'type_'."""
        config = output["fieldsets"]["dma::regs::Config"]
        field_names = {f["name"] for f in config["fields"]}
        assert "type_" in field_names, (
            f"Expected keyword-escaped field 'type_' in Config, got {field_names}"
        )
        assert "type" not in field_names, (
            "Field 'type' should be escaped to 'type_'"
        )

    def test_no_screaming_snake_block_keys(self, output):
        for key in output["blocks"]:
            assert "DMA0" not in key, f"Unsanitized block key: {key}"

    def test_no_screaming_snake_fieldset_keys(self, output):
        for key in output["fieldsets"]:
            assert "DMA0" not in key, f"Unsanitized fieldset key: {key}"

    def test_no_screaming_snake_enum_keys(self, output):
        for key in output["enums"]:
            assert "DMA0" not in key, f"Unsanitized enum key: {key}"


# ── Useless fieldset deletion ───────────────────────────────────

class TestUselessDeletion:
    def test_no_src_addr_fieldsets(self, output):
        for name in output["fieldsets"]:
            assert "SrcAddr" not in name, (
                f"Useless SrcAddr fieldset not deleted: {name}"
            )

    def test_no_dst_addr_fieldsets(self, output):
        for name in output["fieldsets"]:
            assert "DstAddr" not in name, (
                f"Useless DstAddr fieldset not deleted: {name}"
            )

    def test_src_addr_register_fieldset_cleared(self, output):
        """Registers whose useless fieldset was deleted should have null fieldset."""
        channel = output["blocks"]["dma::Channel"]
        src = next(i for i in channel["items"] if i["name"] == "src_addr")
        assert src["inner"]["type"] == "register"
        assert src["inner"].get("fieldset") is None, (
            f"src_addr fieldset ref should be cleared, got {src['inner'].get('fieldset')}"
        )

    def test_dst_addr_register_fieldset_cleared(self, output):
        channel = output["blocks"]["dma::Channel"]
        dst = next(i for i in channel["items"] if i["name"] == "dst_addr")
        assert dst["inner"]["type"] == "register"
        assert dst["inner"].get("fieldset") is None, (
            f"dst_addr fieldset ref should be cleared, got {dst['inner'].get('fieldset')}"
        )


# ── Single-bit enum deletion ───────────────────────────────────

class TestBitSizeEnumDeletion:
    def test_no_enable_enums(self, output):
        for name in output["enums"]:
            assert "En" not in name.split("::")[-1] or "ErrorCode" in name, (
                f"Single-bit enum not deleted: {name}"
            )

    def test_en_field_enum_cleared(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        en_field = next(f for f in ctrl["fields"] if f["name"] == "en")
        assert en_field.get("enum") is None, (
            f"en field enum ref should be cleared after bit_size:1 deletion, "
            f"got {en_field.get('enum')}"
        )


# ── Debug deletion ──────────────────────────────────────────────

class TestDebugDeletion:
    def test_no_debug_register_items(self, output):
        for block_name, block in output["blocks"].items():
            for item in block["items"]:
                assert "debug" not in item["name"].lower(), (
                    f"Found debug register '{item['name']}' in block '{block_name}'"
                )

    def test_no_debug_fieldsets(self, output):
        for name in output["fieldsets"]:
            assert "Debug" not in name.split("::")[-1], (
                f"Found debug fieldset: {name}"
            )


# ── Field renaming (channel prefix stripped) ────────────────────

class TestFieldRenaming:
    def test_ctrl_fields_no_channel_prefix(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        for field in ctrl["fields"]:
            assert not re.match(r"ch\d+_", field["name"]), (
                f"Field '{field['name']}' still has channel prefix"
            )

    def test_ctrl_field_names(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        field_names = {f["name"] for f in ctrl["fields"]}
        expected = {"en", "mode", "priority", "burst_size", "src_inc", "dst_inc", "circ"}
        assert field_names == expected, (
            f"Expected ChCtrl fields {expected}, got {field_names}"
        )


# ── Block structure ─────────────────────────────────────────────

class TestBlockStructure:
    def test_block_count(self, output):
        assert len(output["blocks"]) == 2, (
            f"Expected 2 blocks (dma::Dma + dma::Channel), got {len(output['blocks'])}: "
            f"{list(output['blocks'].keys())}"
        )

    def test_dma_block_exists(self, output):
        assert "dma::Dma" in output["blocks"]

    def test_channel_block_exists(self, output):
        assert "dma::Channel" in output["blocks"]

    def test_dma_block_item_count(self, output):
        dma = output["blocks"]["dma::Dma"]
        assert len(dma["items"]) == 5, (
            f"Expected 5 items (ch, enable, int_status, int_enable, config), "
            f"got {len(dma['items'])}: {[i['name'] for i in dma['items']]}"
        )

    def test_dma_block_item_names(self, output):
        dma = output["blocks"]["dma::Dma"]
        names = {i["name"] for i in dma["items"]}
        expected = {"ch", "enable", "int_status", "int_enable", "config"}
        assert names == expected, f"Expected items {expected}, got {names}"

    def test_channel_block_item_count(self, output):
        channel = output["blocks"]["dma::Channel"]
        assert len(channel["items"]) == 5, (
            f"Expected 5 items (ctrl, status, src_addr, dst_addr, xfer_count), "
            f"got {len(channel['items'])}: {[i['name'] for i in channel['items']]}"
        )

    def test_channel_block_item_names(self, output):
        channel = output["blocks"]["dma::Channel"]
        names = {i["name"] for i in channel["items"]}
        expected = {"ctrl", "status", "src_addr", "dst_addr", "xfer_count"}
        assert names == expected, f"Expected items {expected}, got {names}"


# ── Register offsets ────────────────────────────────────────────

class TestRegisterOffsets:
    def test_channel_register_offsets(self, output):
        channel = output["blocks"]["dma::Channel"]
        items = sorted(channel["items"], key=lambda i: i["byte_offset"])
        expected = [
            ("ctrl", 0),
            ("status", 4),
            ("src_addr", 8),
            ("dst_addr", 12),
            ("xfer_count", 16),
        ]
        for item, (exp_name, exp_offset) in zip(items, expected):
            assert item["name"] == exp_name, (
                f"At offset {exp_offset}: expected '{exp_name}', got '{item['name']}'"
            )
            assert item["byte_offset"] == exp_offset, (
                f"Item '{exp_name}': expected offset {exp_offset}, got {item['byte_offset']}"
            )

    def test_global_register_offsets(self, output):
        dma = output["blocks"]["dma::Dma"]
        expected_offsets = {
            "enable": 256,
            "int_status": 260,
            "int_enable": 264,
            "config": 268,
        }
        for item in dma["items"]:
            if item["name"] in expected_offsets:
                assert item["byte_offset"] == expected_offsets[item["name"]], (
                    f"Item '{item['name']}': expected offset "
                    f"{expected_offsets[item['name']]}, got {item['byte_offset']}"
                )


# ── Array properties ────────────────────────────────────────────

class TestArrayProperties:
    def _get_ch_item(self, output):
        dma = output["blocks"]["dma::Dma"]
        return next(i for i in dma["items"] if i["name"] == "ch")

    def test_ch_byte_offset(self, output):
        ch = self._get_ch_item(output)
        assert ch["byte_offset"] == 0

    def test_ch_is_block_reference(self, output):
        ch = self._get_ch_item(output)
        assert ch["inner"]["type"] == "block"
        assert ch["inner"]["block"] == "dma::Channel"

    def test_ch_array_len(self, output):
        ch = self._get_ch_item(output)
        assert "array" in ch, "ch item must have an array field"
        assert ch["array"]["len"] == 4

    def test_ch_array_stride(self, output):
        ch = self._get_ch_item(output)
        assert ch["array"]["stride"] == 32, (
            f"Expected stride 32 (0x20), got {ch['array']['stride']}"
        )


# ── Fieldset merging ────────────────────────────────────────────

class TestFieldsets:
    def test_fieldset_count(self, output):
        assert len(output["fieldsets"]) == 7, (
            f"Expected 7 fieldsets, got {len(output['fieldsets'])}: "
            f"{list(output['fieldsets'].keys())}"
        )

    def test_merged_fieldsets_exist(self, output):
        for name in ["dma::regs::ChCtrl", "dma::regs::ChStatus", "dma::regs::ChXferCount"]:
            assert name in output["fieldsets"], f"Missing merged fieldset: {name}"

    def test_global_fieldsets_exist(self, output):
        for name in [
            "dma::regs::Enable",
            "dma::regs::IntStatus",
            "dma::regs::IntEnable",
            "dma::regs::Config",
        ]:
            assert name in output["fieldsets"], f"Missing global fieldset: {name}"

    def test_no_per_channel_fieldsets(self, output):
        for name in output["fieldsets"]:
            assert not re.match(r".*::Ch\d+(Ctrl|Status|XferCount|Debug)", name), (
                f"Found per-channel fieldset: {name}"
            )

    def test_ch_status_fields(self, output):
        status = output["fieldsets"]["dma::regs::ChStatus"]
        field_names = {f["name"] for f in status["fields"]}
        expected = {"busy", "error", "error_code", "bytes_remaining"}
        assert field_names == expected

    def test_ch_xfer_count_fields(self, output):
        xfer = output["fieldsets"]["dma::regs::ChXferCount"]
        field_names = {f["name"] for f in xfer["fields"]}
        expected = {"count", "remaining"}
        assert field_names == expected


# ── Enum merging ────────────────────────────────────────────────

class TestEnums:
    def test_enum_count(self, output):
        assert len(output["enums"]) == 5, (
            f"Expected 5 enums, got {len(output['enums'])}: "
            f"{list(output['enums'].keys())}"
        )

    def test_merged_enums_exist(self, output):
        for name in [
            "dma::vals::Mode",
            "dma::vals::Priority",
            "dma::vals::BurstSize",
            "dma::vals::ErrorCode",
        ]:
            assert name in output["enums"], f"Missing merged enum: {name}"

    def test_arb_mode_enum_exists(self, output):
        assert "dma::vals::ArbMode" in output["enums"]

    def test_no_per_channel_enums(self, output):
        for name in output["enums"]:
            assert not re.match(r".*::Ch\d+", name), (
                f"Found per-channel enum: {name}"
            )

    def test_mode_enum_variants_pascal(self, output):
        mode = output["enums"]["dma::vals::Mode"]
        variant_names = {v["name"] for v in mode["variants"]}
        expected = {"MemToMem", "MemToPeriph", "PeriphToMem", "PeriphToPeriph"}
        assert variant_names == expected, (
            f"Expected PascalCase variants {expected}, got {variant_names}"
        )

    def test_priority_enum_variants_pascal(self, output):
        prio = output["enums"]["dma::vals::Priority"]
        variant_names = {v["name"] for v in prio["variants"]}
        expected = {"Low", "Medium", "High", "VeryHigh"}
        assert variant_names == expected, (
            f"Expected PascalCase variants {expected}, got {variant_names}"
        )

    def test_burst_size_enum_variants_pascal(self, output):
        burst = output["enums"]["dma::vals::BurstSize"]
        variant_names = {v["name"] for v in burst["variants"]}
        expected = {"Single", "Incr4", "Incr8", "Incr16"}
        assert variant_names == expected, (
            f"Expected PascalCase variants {expected}, got {variant_names}"
        )

    def test_error_code_enum_variants_pascal(self, output):
        ec = output["enums"]["dma::vals::ErrorCode"]
        variant_names = {v["name"] for v in ec["variants"]}
        expected = {"None", "BusError", "AlignError", "ConfigError"}
        assert variant_names == expected, (
            f"Expected PascalCase variants {expected}, got {variant_names}"
        )

    def test_arb_mode_enum_variants_pascal(self, output):
        arb = output["enums"]["dma::vals::ArbMode"]
        variant_names = {v["name"] for v in arb["variants"]}
        expected = {"Fixed", "RoundRobin"}
        assert variant_names == expected, (
            f"Expected PascalCase variants {expected}, got {variant_names}"
        )


# ── Cross-reference integrity ──────────────────────────────────

class TestReferenceIntegrity:
    def test_all_fieldset_references_valid(self, output):
        valid_fieldsets = set(output["fieldsets"].keys())
        for block_name, block in output["blocks"].items():
            for item in block["items"]:
                if item["inner"]["type"] == "register":
                    fs = item["inner"].get("fieldset")
                    if fs:
                        assert fs in valid_fieldsets, (
                            f"Block '{block_name}', item '{item['name']}': "
                            f"dangling fieldset ref '{fs}'"
                        )

    def test_all_enum_references_valid(self, output):
        valid_enums = set(output["enums"].keys())
        for fs_name, fs in output["fieldsets"].items():
            for field in fs["fields"]:
                enum_ref = field.get("enum")
                if enum_ref:
                    assert enum_ref in valid_enums, (
                        f"Fieldset '{fs_name}', field '{field['name']}': "
                        f"dangling enum ref '{enum_ref}'"
                    )

    def test_all_block_references_valid(self, output):
        valid_blocks = set(output["blocks"].keys())
        for block_name, block in output["blocks"].items():
            for item in block["items"]:
                if item["inner"]["type"] == "block":
                    ref = item["inner"]["block"]
                    assert ref in valid_blocks, (
                        f"Block '{block_name}', item '{item['name']}': "
                        f"dangling block ref '{ref}'"
                    )


# ── Merged references ──────────────────────────────────────────

class TestMergedReferences:
    def test_ctrl_mode_enum_ref(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        mode_field = next(f for f in ctrl["fields"] if f["name"] == "mode")
        assert mode_field["enum"] == "dma::vals::Mode"

    def test_ctrl_priority_enum_ref(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        prio_field = next(f for f in ctrl["fields"] if f["name"] == "priority")
        assert prio_field["enum"] == "dma::vals::Priority"

    def test_ctrl_burst_size_enum_ref(self, output):
        ctrl = output["fieldsets"]["dma::regs::ChCtrl"]
        burst_field = next(f for f in ctrl["fields"] if f["name"] == "burst_size")
        assert burst_field["enum"] == "dma::vals::BurstSize"

    def test_status_error_code_enum_ref(self, output):
        status = output["fieldsets"]["dma::regs::ChStatus"]
        ec_field = next(f for f in status["fields"] if f["name"] == "error_code")
        assert ec_field["enum"] == "dma::vals::ErrorCode"

    def test_config_arb_mode_enum_ref(self, output):
        config = output["fieldsets"]["dma::regs::Config"]
        arb_field = next(f for f in config["fields"] if f["name"] == "arb_mode")
        assert arb_field["enum"] == "dma::vals::ArbMode"

    def test_ctrl_fieldset_in_channel_block(self, output):
        channel = output["blocks"]["dma::Channel"]
        ctrl_item = next(i for i in channel["items"] if i["name"] == "ctrl")
        assert ctrl_item["inner"]["type"] == "register"
        assert ctrl_item["inner"]["fieldset"] == "dma::regs::ChCtrl"

    def test_status_fieldset_in_channel_block(self, output):
        channel = output["blocks"]["dma::Channel"]
        status_item = next(i for i in channel["items"] if i["name"] == "status")
        assert status_item["inner"]["type"] == "register"
        assert status_item["inner"]["fieldset"] == "dma::regs::ChStatus"

    def test_xfer_count_fieldset_in_channel_block(self, output):
        channel = output["blocks"]["dma::Channel"]
        xfer_item = next(i for i in channel["items"] if i["name"] == "xfer_count")
        assert xfer_item["inner"]["type"] == "register"
        assert xfer_item["inner"]["fieldset"] == "dma::regs::ChXferCount"


# ── Access modes preserved ─────────────────────────────────────

class TestAccessModes:
    def test_ctrl_is_readwrite(self, output):
        channel = output["blocks"]["dma::Channel"]
        ctrl = next(i for i in channel["items"] if i["name"] == "ctrl")
        assert ctrl["inner"]["access"] == "ReadWrite"

    def test_status_is_read(self, output):
        channel = output["blocks"]["dma::Channel"]
        status = next(i for i in channel["items"] if i["name"] == "status")
        assert status["inner"]["access"] == "Read"

    def test_int_status_is_read(self, output):
        dma = output["blocks"]["dma::Dma"]
        int_status = next(i for i in dma["items"] if i["name"] == "int_status")
        assert int_status["inner"]["access"] == "Read"


# ── No unsanitized references anywhere ─────────────────────────

class TestNoUnsanitizedReferences:
    def test_no_dma0_anywhere(self, output):
        json_str = json.dumps(output)
        assert "DMA0" not in json_str, "Found unsanitized 'DMA0' in output"

    def test_no_screaming_snake_variants(self, output):
        for ename, enum in output["enums"].items():
            for v in enum["variants"]:
                assert v["name"] != v["name"].upper() or len(v["name"]) <= 1, (
                    f"Enum '{ename}' variant '{v['name']}' appears unsanitized"
                )
