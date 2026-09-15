use std::io::Read;

fn main() {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let tree = resilient_ll_parsing::parse(&input);
    print!("{tree:?}");
}
