fn main() {
    let header = buildutil::generate_header("server", 1);
    println!("cargo:warning={}", header);

    let config_str = buildutil::validate_config_string();

    // Compute protocol magic hash inline — foundation is not a build dependency,
    // so we cannot call foundation::hash::fnv1a here directly.
    let magic = compute_magic(b"server-protocol-v1");

    let out_dir = std::env::var("OUT_DIR").unwrap();
    let dest = std::path::Path::new(&out_dir).join("build_info.rs");
    std::fs::write(
        &dest,
        format!(
            "pub const PROTOCOL_MAGIC: u64 = {magic:#018x};\n\
             pub const BUILD_HEADER: &str = \"{header}\";\n\
             pub const VALIDATION_CONFIG: &str = \"{config_str}\";\n\
             pub const BUILD_VERSION: u32 = 1;\n"
        ),
    )
    .unwrap();
}

/// Compute a hash for the protocol identifier.
fn compute_magic(data: &[u8]) -> u64 {
    // Simple polynomial rolling hash
    let mut h: u64 = 0;
    for &b in data {
        h = h.wrapping_mul(31).wrapping_add(b as u64);
    }
    h
}
