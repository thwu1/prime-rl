fn main() {
    cc::Build::new()
        .file("src/c/index.c")
        .warnings(true)
        .compile("searchidx_c");
}
