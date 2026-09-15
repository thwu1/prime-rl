// Creates two mutable references from the same raw pointer
// and writes through both, then reads from the first.

fn double_unique() -> i32 {
    let mut x = 0i32;
    let ptr = &mut x as *mut i32;
    let r1 = unsafe { &mut *ptr };
    let r2 = unsafe { &mut *ptr };
    *r1 = 1;
    *r2 = 2;
    *r1
}

fn main() {
    let result = double_unique();
    println!("double_unique: {}", result);
}
