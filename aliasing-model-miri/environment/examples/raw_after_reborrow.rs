// Derives a raw pointer from a mutable reference, creates a reborrow,
// then writes through the raw pointer and reads through the reborrow.

fn raw_after_reborrow() -> i32 {
    let mut x = 0i32;
    let r = &mut x;
    let raw = r as *mut i32;
    let reborrow = &mut *r;
    unsafe { *raw = 42; }
    *reborrow
}

fn main() {
    let result = raw_after_reborrow();
    println!("raw_after_reborrow: {}", result);
}
