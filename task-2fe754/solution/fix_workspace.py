#!/usr/bin/env python3
"""Analyze and fix the signal-processing Cargo workspace architecture.


This script:
1. Reads and analyzes the workspace to diagnose implicit feature dependencies
2. Produces a structured diagnostic report (migration_report.toml)
3. Applies the architectural fixes (resolver v2, workspace deps, code restructuring)
"""

import os
import re
import tomllib


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ============================================================================
# PHASE 1: Diagnostic analysis — evaluate the workspace's feature dependencies
# ============================================================================

root_toml = load_toml("/app/Cargo.toml")
members = root_toml["workspace"]["members"]

# Check if resolver v2 is already set
current_resolver = root_toml.get("workspace", {}).get("resolver")

# Analyze each member's dependencies on signal-core
implicit_features = []

# --- Analyze signal-net ---
net_toml = load_toml("/app/signal-net/Cargo.toml")
net_dev_deps = net_toml.get("dev-dependencies", {})
net_normal_deps = net_toml.get("dependencies", {})

# Find features enabled only via dev-dependencies
dev_only_features = set()
for dep_name, dep_spec in net_dev_deps.items():
    if dep_name == "signal-core" and isinstance(dep_spec, dict):
        dev_feats = set(dep_spec.get("features", []))
        normal_core = net_normal_deps.get("signal-core", {})
        normal_feats = set(normal_core.get("features", []) if isinstance(normal_core, dict) else [])
        dev_only_features = dev_feats - normal_feats

# Check if signal-net source code uses test-utils symbols outside cfg(test)
testfixture_misuse_crate = None
with open("/app/signal-net/src/lib.rs") as f:
    net_src = f.read()

# Find uses of testing::TestFixture not inside #[cfg(test)] blocks
# Simple heuristic: if TestFixture appears before #[cfg(test)] or outside mod tests
lines = net_src.split("\n")
in_cfg_test = False
for line in lines:
    if "#[cfg(test)]" in line:
        in_cfg_test = True
    if "TestFixture" in line and not in_cfg_test:
        testfixture_misuse_crate = "signal-net"
        break

if testfixture_misuse_crate and "test-utils" in dev_only_features:
    implicit_features.append({
        "crate": "signal-net",
        "feature": "test-utils",
        "section": "dev-dependencies",
    })

# Determine which dep section causes the test-utils leak
net_leak_section = "dev-dependencies" if "test-utils" in dev_only_features else "dependencies"

# --- Analyze signal-storage ---
storage_toml = load_toml("/app/signal-storage/Cargo.toml")
storage_core_dep = storage_toml.get("dependencies", {}).get("signal-core", {})
storage_core_features = set()
if isinstance(storage_core_dep, dict):
    storage_core_features = set(storage_core_dep.get("features", []))
elif isinstance(storage_core_dep, str):
    storage_core_features = set()

# Check what signal-core modules signal-storage actually uses
with open("/app/signal-storage/src/lib.rs") as f:
    storage_src = f.read()

# Find which signal_core modules are imported
storage_used_modules = re.findall(r"use signal_core::(\w+)", storage_src)

# Load signal-core to check which modules require which features
with open("/app/signal-core/src/lib.rs") as f:
    core_src = f.read()

# Determine which features each module requires via cfg attributes
storage_missing_feature = None
storage_uses_module = None
for mod_name in storage_used_modules:
    # Check if this module is gated behind a feature
    pattern = rf'#\[cfg\(feature\s*=\s*"(\w+)"\)\]\s*pub\s+mod\s+{mod_name}'
    match = re.search(pattern, core_src)
    if match:
        required_feature = match.group(1)
        if required_feature not in storage_core_features:
            storage_missing_feature = required_feature
            storage_uses_module = mod_name
            implicit_features.append({
                "crate": "signal-storage",
                "feature": required_feature,
                "module": mod_name,
            })

implicit_feature_count = len(implicit_features)

print(f"Diagnostic analysis complete:")
print(f"  Implicit feature dependencies found: {implicit_feature_count}")
print(f"  TestFixture misuse crate: {testfixture_misuse_crate}")
print(f"  Storage missing feature: {storage_missing_feature}")
print(f"  Storage uses module: {storage_uses_module}")
print(f"  Net leak section: {net_leak_section}")


# ============================================================================
# PHASE 2: Write diagnostic report
# ============================================================================

report_content = f"""\
[analysis]
implicit_feature_count = {implicit_feature_count}
testfixture_misuse_crate = "{testfixture_misuse_crate}"
storage_missing_feature = "{storage_missing_feature}"
storage_uses_module = "{storage_uses_module}"
net_leak_section = "{net_leak_section}"
"""

write_file("/app/migration_report.toml", report_content)
print("Wrote /app/migration_report.toml")


# ============================================================================
# PHASE 3: Apply architectural fixes
# ============================================================================

# --- 1. Redesign root Cargo.toml: resolver v2 + workspace.dependencies ---
write_file("/app/Cargo.toml", """\
[workspace]
members = [
    "signal-core",
    "signal-net",
    "signal-storage",
    "signal-embedded",
    "signal-cli",
]
resolver = "2"

[workspace.dependencies]
signal-core = { path = "signal-core" }
serde = { version = "1.0.193", features = ["derive"] }
serde_json = "1.0.108"
""")

# --- 2. Update signal-core/Cargo.toml: use workspace serde ---
write_file("/app/signal-core/Cargo.toml", """\
[package]
name = "signal-core"
version = "0.5.0"
edition = "2021"

[features]
default = ["alloc"]
std = ["alloc"]
alloc = []
serde-support = ["dep:serde"]
test-utils = ["std"]

[dependencies]
serde = { workspace = true, optional = true }
""")

# --- 3. Update signal-net/Cargo.toml: workspace deps ---
write_file("/app/signal-net/Cargo.toml", """\
[package]
name = "signal-net"
version = "0.5.0"
edition = "2021"

[dependencies]
signal-core = { workspace = true, features = ["std", "serde-support"] }
serde = { workspace = true }
serde_json = { workspace = true }

[dev-dependencies]
signal-core = { workspace = true, features = ["test-utils"] }
""")

# --- 4. Restructure signal-net/src/lib.rs: isolate test-only code ---
write_file("/app/signal-net/src/lib.rs", """\
use signal_core::io;
use signal_core::serialization::WireMessage;
use signal_core::types::SignalMessage;

pub struct NetworkTransport {
    buffer: Vec<u8>,
}

impl NetworkTransport {
    pub fn new() -> Self {
        Self { buffer: Vec::new() }
    }

    pub fn send(&mut self, msg: &SignalMessage) -> Result<(), std::io::Error> {
        io::write_message(&mut self.buffer, msg)
    }

    pub fn serialize_message(msg: SignalMessage) -> String {
        let wire: WireMessage = msg.into();
        serde_json::to_string(&wire).unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use signal_core::testing::TestFixture;

    /// Validate that a batch of messages contains no duplicate IDs.
    fn validate_batch(msgs: &[SignalMessage]) -> bool {
        let mut fixture = TestFixture::new();
        for msg in msgs {
            fixture.add(*msg);
        }
        fixture.count() == msgs.len()
    }

    #[test]
    fn test_send() {
        let mut transport = NetworkTransport::new();
        let msg = SignalMessage::new(1, 5);
        transport.send(&msg).unwrap();
        assert!(!transport.buffer.is_empty());
    }

    #[test]
    fn test_serialize() {
        let msg = SignalMessage::new(42, 7);
        let json = NetworkTransport::serialize_message(msg);
        assert!(json.contains("42"));
    }

    #[test]
    fn test_validate_batch_unique() {
        let msgs = vec![
            SignalMessage::new(1, 5),
            SignalMessage::new(2, 3),
            SignalMessage::new(3, 1),
        ];
        assert!(validate_batch(&msgs));
    }

    #[test]
    fn test_validate_batch_duplicates() {
        let msgs = vec![
            SignalMessage::new(1, 5),
            SignalMessage::new(1, 3),
        ];
        assert!(!validate_batch(&msgs));
    }
}
""")

# --- 5. Update signal-storage/Cargo.toml: explicit std + workspace deps ---
write_file("/app/signal-storage/Cargo.toml", """\
[package]
name = "signal-storage"
version = "0.5.0"
edition = "2021"

[dependencies]
signal-core = { workspace = true, features = ["std"] }
serde = { workspace = true }
serde_json = { workspace = true }
""")

# --- 6. Update signal-embedded/Cargo.toml: workspace deps ---
write_file("/app/signal-embedded/Cargo.toml", """\
[package]
name = "signal-embedded"
version = "0.5.0"
edition = "2021"

[dependencies]
signal-core = { workspace = true, default-features = false, features = ["alloc"] }

[build-dependencies]
signal-core = { workspace = true, features = ["std"] }
""")

# --- 7. Update signal-cli/Cargo.toml: workspace deps ---
write_file("/app/signal-cli/Cargo.toml", """\
[package]
name = "signal-cli"
version = "0.5.0"
edition = "2021"

[dependencies]
signal-core = { workspace = true, features = ["std", "serde-support"] }
signal-storage = { path = "../signal-storage" }
serde = { workspace = true }
serde_json = { workspace = true }
""")

print("All workspace architecture changes applied successfully.")
