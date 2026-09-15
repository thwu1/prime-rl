// Copies the first element of an array to the second position.
// Obtains a const pointer via as_ptr(), then a mut pointer via as_mut_ptr().

fn retag_two_phase() -> [i32; 2] {
    let mut arr = [10i32, 20];
    let src = arr.as_ptr();
    let dst = unsafe { arr.as_mut_ptr().add(1) };
    unsafe {
        std::ptr::copy_nonoverlapping(src, dst, 1);
    }
    arr
}

fn main() {
    let result = retag_two_phase();
    println!("retag_two_phase: {:?}", result);
}
