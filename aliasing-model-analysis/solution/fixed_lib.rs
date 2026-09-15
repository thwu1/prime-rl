
use std::ptr;

/// Fix for interleaved_copy (was SB-only UB):
/// Original derived src from as_ptr() and dst from as_mut_ptr(). Under Stacked
/// Borrows, as_mut_ptr()'s mutable reborrow eagerly invalidated src's shared-ref
/// tag on the borrow stack. Fix: derive both src and dst from a single
/// as_mut_ptr() call so they share the same SharedReadWrite provenance.
pub unsafe fn interleaved_copy(data: &mut [i32; 4]) -> i32 {
    let base = data.as_mut_ptr();
    let src = base as *const i32;
    let dst = base.add(2);
    ptr::copy_nonoverlapping(src, dst, 2);
    data[0] + data[1] + data[2] + data[3]
}

/// Fix for activated_overwrite (was TB-only UB):
/// Original wrote through as_mut_ptr() (activating the two-phase borrow in TB),
/// then called as_ptr() which froze the now-Active mutable borrow, making the
/// subsequent write through dst UB. Fix: derive both dst and src from a single
/// as_mut_ptr() before any writes, avoiding re-borrowing via as_ptr().
pub unsafe fn activated_overwrite(data: &mut [i32; 4]) -> i32 {
    let base = data.as_mut_ptr();
    let dst = base;
    let src = base.add(1) as *const i32;
    *dst = 0;
    let val = *src;
    *dst = val;
    data[0] + data[1] + data[2] + data[3]
}

/// Fix for reborrow_invalidation (was UB under both models):
/// Original read through `child` after `parent` had invalidated it. Under SB,
/// *parent pops child's tag from the borrow stack. Under TB, *parent is a parent
/// write that disables child's tree node. Fix: read through parent instead of
/// child after the parent write.
pub unsafe fn reborrow_invalidation() -> i32 {
    let mut val = 42i32;
    let parent: *mut i32 = &mut val;
    let child: *mut i32 = &mut *parent;
    *child = 5;
    *parent = 3;
    *parent
}

/// No fix needed (was neither UB under either model):
/// All raw pointers derived from a single as_mut_ptr() call and used on
/// disjoint array elements. Valid under both aliasing models.
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

/// Fix for shared_read_after_mut (was SB-only UB):
/// Same pattern as interleaved_copy — shared-ref-derived pointers from as_ptr()
/// were invalidated by the subsequent as_mut_ptr() call under Stacked Borrows.
/// Fix: derive all pointers from a single as_mut_ptr() call.
pub unsafe fn shared_read_after_mut(data: &mut [i32; 4]) -> i32 {
    let base = data.as_mut_ptr();
    let src1 = base.add(1) as *const i32;
    let src2 = base.add(2) as *const i32;
    let val = *src1 + *src2;
    *base = val;
    data[0]
}

/// Fix for protector_violation (was UB under both models):
/// Original passed both &mut val and an aliasing raw pointer to protector_inner.
/// The &mut argument gets a protector in both models. Writing through the aliasing
/// raw pointer invalidates the protected &mut — UB. Fix: pass only a raw pointer,
/// eliminating the protector conflict.
pub unsafe fn protector_violation() -> i32 {
    let mut val = 0i32;
    let raw = &mut val as *mut i32;
    protector_inner(raw)
}

unsafe fn protector_inner(raw: *mut i32) -> i32 {
    *raw = 100;
    *raw = 200;
    *raw
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
