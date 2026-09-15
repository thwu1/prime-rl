//! Geometric algebra core kernel — FIXED VERSION.
//!
//! Provides FFI-callable functions for multivector operations over
//! configurable metric signatures (VGA, PGA, general Clifford algebras).
//!
//! Multivectors are stored as flat f64 arrays ordered by a blade-ordering
//! convention computed by `compute_tables`.

/// Compute blade ordering tables for `dims` dimensions.
///
/// Returns (mask_table, inv_mask_table) where:
///   mask_table[position] = bitmask of the basis blade at that position
///   inv_mask_table[bitmask] = position of that basis blade
///
/// Blades are ordered by ascending grade, with a canonical within-grade
/// ordering established by sweeping each dimension from high to low.
fn compute_tables(dims: u32) -> (Vec<u32>, Vec<usize>) {
    let n = 1usize << dims;
    let mut table: Vec<u32> = (0..n as u32).collect();

    // FIX: sweep dimensions from high to low for correct within-grade ordering
    for d in (0..dims).rev() {
        let dim_mask = 1u32 << d;
        table.sort_by_key(|&a| if (a & dim_mask) != 0 { 0u32 } else { 1u32 });
    }
    table.sort_by_key(|&a| a.count_ones());

    let mut inv = vec![0usize; n];
    for (i, &v) in table.iter().enumerate() {
        inv[v as usize] = i;
    }
    (table, inv)
}

/// Fill pre-allocated arrays with blade ordering tables.
#[no_mangle]
pub extern "C" fn ga_mask_tables(
    dims: u32,
    mask_table_out: *mut u32,
    inv_table_out: *mut u32,
) {
    let (table, inv) = compute_tables(dims);
    let n = table.len();
    unsafe {
        for i in 0..n {
            *mask_table_out.add(i) = table[i];
            *inv_table_out.add(i) = inv[i] as u32;
        }
    }
}

/// Grade (popcount) of a basis blade bitmask.
#[no_mangle]
pub extern "C" fn ga_blade_grade(bitmask: u32) -> u32 {
    bitmask.count_ones()
}

/// Sign factor from reordering the concatenation of two basis blades into
/// canonical order.
#[no_mangle]
pub extern "C" fn ga_reorder_sign(mask_a: u32, mask_b: u32) -> i32 {
    let mut shifted = mask_a >> 1;
    let mut count = 0u32;
    while shifted != 0 {
        count += (shifted & mask_b).count_ones();
        // FIX: shift by 1, not 2
        shifted >>= 1;
    }
    if count % 2 == 0 { 1 } else { -1 }
}

/// Metric value (square of a basis vector) for a given algebra flavor.
#[no_mangle]
pub extern "C" fn ga_metric(
    flavor: u32,
    _p: u32,
    q: u32,
    r: u32,
    bit_index: u32,
) -> i32 {
    match flavor {
        0 => 1,
        1 => {
            if bit_index == 0 { 0 } else { 1 }
        }
        2 => {
            if bit_index < r {
                0
            } else {
                let idx = bit_index - r;
                if idx < q { -1 } else { 1 }
            }
        }
        _ => 1,
    }
}

/// Core product kernel with configurable grade filtering.
#[no_mangle]
pub extern "C" fn ga_product_core(
    mv_a: *const f64,
    mv_b: *const f64,
    result: *mut f64,
    n: u32,
    dims: u32,
    flavor: u32,
    p: u32,
    q: u32,
    r: u32,
    mode: u32,
) {
    let n = n as usize;
    let (table, inv) = compute_tables(dims);

    for i in 0..n {
        unsafe { *result.add(i) = 0.0; }
    }

    for i in 0..n {
        let ai = unsafe { *mv_a.add(i) };
        if ai == 0.0 { continue; }
        let mi = table[i];
        let gi = mi.count_ones();

        for j in 0..n {
            let bj = unsafe { *mv_b.add(j) };
            if bj == 0.0 { continue; }
            let mj = table[j];
            let gj = mj.count_ones();

            let common = mi & mj;
            let result_mask = mi ^ mj;
            let gr = result_mask.count_ones();

            let pass = match mode {
                0 => true,
                1 => gr == gi + gj,
                2 => gi > 0 && gj > 0 && gr == gi.abs_diff(gj),
                _ => true,
            };
            if !pass { continue; }

            // FIX: iterate over common (shared basis vectors), not result_mask
            let mut met = 1i32;
            let mut temp = common;
            let mut bit = 0u32;
            while temp != 0 {
                if temp & 1 != 0 {
                    let m = ga_metric(flavor, p, q, r, bit);
                    if m == 0 {
                        met = 0;
                        break;
                    }
                    met *= m;
                }
                temp >>= 1;
                bit += 1;
            }
            if met == 0 { continue; }

            let sign = ga_reorder_sign(mi, mj);

            unsafe {
                *result.add(inv[result_mask as usize]) += (sign * met) as f64 * ai * bj;
            }
        }
    }
}
