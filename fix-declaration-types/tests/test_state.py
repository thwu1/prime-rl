
import subprocess
import hashlib
import os

EXPECTED_HASHES = {
    "/app/src/consumer.ts": "19db64fa5c2faba17f68544ce48a69020ab1fafd24b2f8e382707b3a047e804f",
    "/app/src/negative.ts": "e15f7766d2fe5c2c60073c8d728014f83e2a0a51b3ea1858e0e696b1b1e5e423",
    "/app/src/umd-global.ts": "c88854953155a7d558a261636e156ca10d2ddf98d4d7568f94b39a8a054daff9",
    "/app/src/plugin-consumer.ts": "bac970484a3729c6f7e5af465d623df76dc2b4090f2bebbe49f97ee5d148b249",
    "/app/tsconfig.json": "ba1547ab4cf60fb3aab496e693d8c60deafc367af6c0d8538a7d7f402ea1bbe5",
    "/app/lib/sigil.js": "46fd0170edb2a5c1700be7a346534696b5bae7ee0e904f07e446471fe27f4b41",
    "/app/plugins/sigil-persist.js": "dac49d18edd1ecbed2f26f07fb6b0fc38d2f43d8594ca1752409c9b1800d0301",
}


def test_main_declaration_file_exists():
    """The main declaration file must exist at the expected path."""
    assert os.path.exists("/app/lib/sigil.d.ts"), (
        "sigil.d.ts not found at /app/lib/sigil.d.ts. "
        "Create the declaration file at that path."
    )


def test_plugin_declaration_file_exists():
    """The plugin declaration file must exist at the expected path."""
    assert os.path.exists("/app/plugins/sigil-persist.d.ts"), (
        "sigil-persist.d.ts not found at /app/plugins/sigil-persist.d.ts. "
        "Create the plugin declaration file at that path."
    )


def test_source_files_not_modified():
    """Consumer files, source JS, and tsconfig must not be modified."""
    for path, expected_hash in EXPECTED_HASHES.items():
        assert os.path.exists(path), f"{path} is missing"
        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        assert actual_hash == expected_hash, (
            f"{path} was modified (hash mismatch). "
            f"Only /app/lib/sigil.d.ts and /app/plugins/sigil-persist.d.ts may be created."
        )


def test_tsc_compiles_successfully():
    """tsc --noEmit must exit with code 0 (no type errors)."""
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"tsc --noEmit failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_main_declaration_contains_typescript_syntax():
    """Main declaration file must contain TypeScript declaration syntax."""
    with open("/app/lib/sigil.d.ts") as f:
        content = f.read()
    assert "Signal" in content, "Declaration must define Signal type"
    assert "interface" in content or "type" in content, (
        "Declaration must use TypeScript type constructs"
    )
    assert "export" in content, "Declaration must export the module"


def test_plugin_declaration_contains_augmentation():
    """Plugin declaration must augment the sigil module."""
    with open("/app/plugins/sigil-persist.d.ts") as f:
        content = f.read()
    assert "sigil" in content, "Plugin must reference the sigil module"
    assert "persist" in content, "Plugin must declare persist method"
    assert "snapshot" in content or "Snapshot" in content, (
        "Plugin must declare snapshot functionality"
    )


def test_js_runtime_unchanged():
    """The JavaScript runtime files must not be deleted."""
    assert os.path.exists("/app/lib/sigil.js"), "sigil.js must not be deleted"
    assert os.path.exists("/app/plugins/sigil-persist.js"), (
        "sigil-persist.js must not be deleted"
    )


def test_main_declaration_not_trivially_any():
    """Main declaration must not abuse 'any' type to bypass precision checks."""
    with open("/app/lib/sigil.d.ts") as f:
        content = f.read()
    lines_with_any = [
        line.strip() for line in content.split('\n')
        if 'any' in line
        and not line.strip().startswith('//')
        and not line.strip().startswith('*')
    ]
    assert len(lines_with_any) < 12, (
        f"Main declaration uses 'any' on {len(lines_with_any)} lines. "
        f"A correct solution uses precise types; 'any' should appear "
        f"only in generic constraints and fallback handler signatures."
    )


def test_plugin_declaration_not_trivially_any():
    """Plugin declaration must not abuse 'any' type."""
    with open("/app/plugins/sigil-persist.d.ts") as f:
        content = f.read()
    lines_with_any = [
        line.strip() for line in content.split('\n')
        if 'any' in line
        and not line.strip().startswith('//')
        and not line.strip().startswith('*')
    ]
    assert len(lines_with_any) < 5, (
        f"Plugin declaration uses 'any' on {len(lines_with_any)} lines. "
        f"A correct solution uses precise types."
    )


def test_no_extra_files_created():
    """Only the two declaration files should be created."""
    import glob
    src_ts = set(glob.glob("/app/src/*.ts"))
    expected_ts = {
        "/app/src/consumer.ts",
        "/app/src/negative.ts",
        "/app/src/umd-global.ts",
        "/app/src/plugin-consumer.ts",
    }
    extra = src_ts - expected_ts
    assert not extra, f"Unexpected .ts files created in src/: {extra}"
