// Derives a raw pointer from a mutable reference, writes through
// the raw pointer, then reads the local variable directly.

fn sound_mutation() -> i32 {
    let mut x = 0i32;
    let r = &mut x;
    let raw = r as *mut i32;
    unsafe { *raw = 42; }
    x
}

fn main() {
    let result = sound_mutation();
    println!("sound_mutation: {}", result);
}
