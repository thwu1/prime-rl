// Creates a raw pointer to a local variable via addr_of_mut!,
// writes to the local directly, then reads through the raw pointer.

fn local_addr_of() -> i32 {
    let mut x = 0i32;
    let ptr = std::ptr::addr_of_mut!(x);
    x = 42;
    unsafe { ptr.read() }
}

fn main() {
    let result = local_addr_of();
    println!("local_addr_of: {}", result);
}
