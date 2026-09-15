// Fixed versions of all functions that had UB under at least one aliasing model.
// Each function is sound under both Stacked Borrows and Tree Borrows.

/// Fixed retag_two_phase: derive both src and dst from a single as_mut_ptr() call.
/// This avoids the conflict between as_ptr()'s shared borrow and as_mut_ptr()'s
/// exclusive borrow that caused UB under Stacked Borrows.
fn retag_two_phase_fixed() -> [i32; 2] {
    let mut arr = [10i32, 20];
    let base = arr.as_mut_ptr();
    let src = base as *const i32;
    let dst = unsafe { base.add(1) };
    unsafe {
        std::ptr::copy_nonoverlapping(src, dst, 1);
    }
    arr
}

/// Fixed write_then_ref: derive both src and dst from a single as_mut_ptr() call.
/// This avoids the conflict where writing through dst activated the two-phase borrow
/// and then creating a shared ref via as_ptr() made dst read-only under Tree Borrows.
fn write_then_ref_fixed() -> [i32; 2] {
    let mut arr = [10i32, 20];
    let base = arr.as_mut_ptr();
    let dst = unsafe { base.add(1) };
    let src = base as *const i32;
    unsafe { dst.write(0); }
    unsafe {
        std::ptr::copy_nonoverlapping(src, dst, 1);
    }
    arr
}

/// Fixed local_addr_of: perform all operations through the raw pointer only,
/// avoiding the interleaving of direct local writes with raw pointer reads
/// that caused UB under Stacked Borrows.
fn local_addr_of_fixed() -> i32 {
    let mut x = 0i32;
    let ptr = std::ptr::addr_of_mut!(x);
    unsafe {
        ptr.write(42);
        ptr.read()
    }
}

/// Fixed double_unique: use a single raw pointer for all writes and reads
/// instead of creating two conflicting mutable references.
fn double_unique_fixed() -> i32 {
    let mut x = 0i32;
    let ptr = &mut x as *mut i32;
    unsafe {
        ptr.write(1);
        ptr.write(2);
        ptr.read()
    }
}

/// Fixed raw_after_reborrow: don't create a reborrow that conflicts with
/// the raw pointer. Read back through the raw pointer instead.
fn raw_after_reborrow_fixed() -> i32 {
    let mut x = 0i32;
    let r = &mut x;
    let raw = r as *mut i32;
    unsafe {
        *raw = 42;
        *raw
    }
}
