// Zeros the second element of an array, then copies the first element to the second.
// Obtains as_mut_ptr() first, writes through it, then obtains as_ptr().

fn write_then_ref() -> [i32; 2] {
    let mut arr = [10i32, 20];
    let dst = unsafe { arr.as_mut_ptr().add(1) };
    unsafe { dst.write(0); }
    let src = arr.as_ptr();
    unsafe {
        std::ptr::copy_nonoverlapping(src, dst, 1);
    }
    arr
}

fn main() {
    let result = write_then_ref();
    println!("write_then_ref: {:?}", result);
}
