
use std::ptr;

/// Copies the first two elements of the array to positions 2 and 3 using
/// raw pointers derived from separate as_ptr / as_mut_ptr calls.
/// For input [1,2,3,4] the result is [1,2,1,2], returning sum = 6.
pub unsafe fn interleaved_copy(data: &mut [i32; 4]) -> i32 {
    let src = data.as_ptr();
    let dst = data.as_mut_ptr().add(2);
    ptr::copy_nonoverlapping(src, dst, 2);
    data[0] + data[1] + data[2] + data[3]
}

/// Writes through a raw pointer derived from as_mut_ptr, then creates a shared
/// reference via as_ptr to read another element, then writes again through the
/// original pointer. For input [10,20,30,40] returns sum = 110.
pub unsafe fn activated_overwrite(data: &mut [i32; 4]) -> i32 {
    let dst = data.as_mut_ptr();
    *dst = 0;
    let val = *data.as_ptr().add(1);
    *dst = val;
    data[0] + data[1] + data[2] + data[3]
}

/// Creates a parent raw pointer and a child reborrow from it, writes through
/// both in sequence, then reads through the child after the parent has
/// invalidated it. Returns 3.
pub unsafe fn reborrow_invalidation() -> i32 {
    let mut val = 42i32;
    let parent: *mut i32 = &mut val;
    let child: *mut i32 = &mut *parent;
    *child = 5;
    *parent = 3;
    *child
}

/// Derives multiple raw pointers from a single as_mut_ptr call and uses them
/// to swap elements in an array. Returns the sum (expected: 100).
pub unsafe fn disjoint_raw_ptrs() -> i32 {
    let mut a = [10i32, 20, 30, 40];
    let base = a.as_mut_ptr();
    let p0 = base;
    let p3 = base.add(3);
    let tmp = *p0;
    *p0 = *p3;
    *p3 = tmp;
    a[0] + a[1] + a[2] + a[3]
}

/// Reads from two shared-reference-derived pointers created before a mutable
/// pointer, sums the values, and writes the sum through the mutable pointer.
/// For input [5,10,15,20] returns 25.
pub unsafe fn shared_read_after_mut(data: &mut [i32; 4]) -> i32 {
    let src1 = data.as_ptr().add(1);
    let src2 = data.as_ptr().add(2);
    let dst = data.as_mut_ptr();
    let val = *src1 + *src2;
    *dst = val;
    data[0]
}

/// Passes an aliasing &mut reference and raw pointer into a helper function
/// where the mutable reference has a protector. Returns 200.
pub unsafe fn protector_violation() -> i32 {
    let mut val = 0i32;
    let raw = &mut val as *mut i32;
    protector_inner(&mut val, raw)
}

unsafe fn protector_inner(r: &mut i32, raw: *mut i32) -> i32 {
    *r = 100;
    *raw = 200;
    *r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_interleaved_copy() {
        let mut data = [1, 2, 3, 4];
        let result = unsafe { interleaved_copy(&mut data) };
        assert_eq!(data, [1, 2, 1, 2]);
        assert_eq!(result, 6);
    }

    #[test]
    fn test_activated_overwrite() {
        let mut data = [10, 20, 30, 40];
        let result = unsafe { activated_overwrite(&mut data) };
        assert_eq!(data[0], 20);
        assert_eq!(result, 110);
    }

    #[test]
    fn test_reborrow_invalidation() {
        let result = unsafe { reborrow_invalidation() };
        assert_eq!(result, 3);
    }

    #[test]
    fn test_disjoint_raw_ptrs() {
        let result = unsafe { disjoint_raw_ptrs() };
        assert_eq!(result, 100);
    }

    #[test]
    fn test_shared_read_after_mut() {
        let mut data = [5, 10, 15, 20];
        let result = unsafe { shared_read_after_mut(&mut data) };
        assert_eq!(result, 25);
    }

    #[test]
    fn test_protector_violation() {
        let result = unsafe { protector_violation() };
        assert_eq!(result, 200);
    }
}
