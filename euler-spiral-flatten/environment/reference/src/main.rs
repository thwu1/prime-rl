//! Test harness — outputs ground-truth values for all key functions.

use euler_flatten_ref::*;

fn main() {
    println!("=== Euler Spiral Reference: Ground Truth Test Vectors ===");
    println!();

    // --- integ_euler_10 ---
    println!("--- integ_euler_10 ---");
    let cases = [
        (0.0, 0.0),
        (0.01, 0.0),
        (0.1, 0.0),
        (0.5, 0.0),
        (1.0, 0.0),
        (-0.5, 0.0),
        (0.0, 0.1),
        (0.3, 0.2),
        (0.5, 0.5),
        (-0.3, 0.1),
        (1.0, -0.5),
    ];
    for (k0, k1) in cases {
        let (u, v) = integ_euler_10(k0, k1);
        println!("  integ_euler_10({:6.2}, {:6.2}) -> u={:.15e}, v={:.15e}", k0, k1, u, v);
    }

    // --- EulerParams ---
    println!();
    println!("--- EulerParams::from_angles ---");
    let angle_cases = [
        (0.0, 0.0),
        (0.1, 0.1),
        (0.2, 0.3),
        (0.5, -0.2),
        (0.01, 0.01),
        (0.3, 0.2),
        (0.2, -0.2),
    ];
    for (th0, th1) in angle_cases {
        let ep = EulerParams::from_angles(th0, th1);
        println!("  from_angles({:5.2}, {:5.2}):", th0, th1);
        println!("    k0={:.15e}  k1={:.15e}  ch={:.15e}", ep.k0, ep.k1, ep.ch);
        println!(
            "    eval_th(0.0)={:.15e}  eval_th(1.0)={:.15e}",
            ep.eval_th(0.0),
            ep.eval_th(1.0)
        );
        let p = ep.eval(1.0);
        println!("    eval(1.0)=({:.15e}, {:.15e})", p.x, p.y);
    }

    // --- espc_int_approx ---
    println!();
    println!("--- espc_int_approx ---");
    let xs = [0.0, 0.1, 0.3, 0.5, 0.7, 0.79, 0.8, 0.9, 1.0, 1.1, 1.24, 1.25, 1.5, 2.0, 2.09, 2.1, 2.5, 3.0, 5.0];
    for x in xs {
        println!("  espc_int_approx({:6.2}) = {:.15e}", x, espc_int_approx(x));
    }

    // --- espc_int_inv_approx roundtrip ---
    println!();
    println!("--- espc_int_inv_approx roundtrip ---");
    let rt_xs = [0.1, 0.3, 0.5, 0.7, 0.9, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0];
    for x in rt_xs {
        let y = espc_int_approx(x);
        let x_back = espc_int_inv_approx(y);
        println!(
            "  x={:.2} -> y={:.15e} -> inv={:.15e}  err={:.2e}",
            x,
            y,
            x_back,
            (x_back - x).abs()
        );
    }

    // --- CubicParams ---
    println!();
    println!("--- CubicParams::from_points_derivs ---");
    {
        let p0 = Vec2::new(0.0, 0.0);
        let p1 = Vec2::new(3.0, 0.0);
        let q0 = Vec2::new(1.0, 0.0);
        let q1 = Vec2::new(1.0, 0.0);
        let cp = CubicParams::from_points_derivs(p0, p1, q0, q1, 1.0);
        println!("  straight line: th0={:.6e} th1={:.6e} chord={:.6} err={:.6e}", cp.th0, cp.th1, cp.chord_len, cp.err);
    }
    {
        let kappa = 0.5522847498;
        let p0 = Vec2::new(1.0, 0.0);
        let p1 = Vec2::new(0.0, 1.0);
        let q0 = Vec2::new(0.0, kappa);
        let q1 = Vec2::new(-kappa, 0.0);
        let cp = CubicParams::from_points_derivs(p0, p1, q0, q1, 1.0);
        println!("  quarter circle: th0={:.6e} th1={:.6e} chord={:.6} err={:.6e}", cp.th0, cp.th1, cp.chord_len, cp.err);
    }

    // --- eval_cubic_and_deriv ---
    println!();
    println!("--- eval_cubic_and_deriv ---");
    {
        let p0 = Vec2::new(0.0, 0.0);
        let p1 = Vec2::new(1.0, 0.0);
        let p2 = Vec2::new(2.0, 1.0);
        let p3 = Vec2::new(3.0, 1.0);
        for t in [0.0, 0.25, 0.5, 0.75, 1.0] {
            let (pt, q) = eval_cubic_and_deriv(p0, p1, p2, p3, t);
            println!(
                "  t={:.2}: pt=({:.12}, {:.12}) q=({:.12}, {:.12})",
                t, pt.x, pt.y, q.x, q.y
            );
        }
    }

    // --- flatten_cubic ---
    println!();
    println!("--- flatten_cubic ---");

    // Quarter circle
    let kappa = 0.5522847498;
    let pts = flatten_cubic(
        Vec2::new(1.0, 0.0),
        Vec2::new(1.0, kappa),
        Vec2::new(kappa, 1.0),
        Vec2::new(0.0, 1.0),
        0.05,
    );
    println!("  quarter_circle (tol=0.05): {} points", pts.len());
    for (i, (x, y)) in pts.iter().enumerate() {
        println!("    [{:2}] ({:.15e}, {:.15e})", i, x, y);
    }

    // S-curve
    let pts = flatten_cubic(
        Vec2::new(0.0, 0.0),
        Vec2::new(1.0, 2.0),
        Vec2::new(2.0, -2.0),
        Vec2::new(3.0, 0.0),
        0.1,
    );
    println!("  s_curve (tol=0.1): {} points", pts.len());
    for (i, (x, y)) in pts.iter().enumerate() {
        println!("    [{:2}] ({:.15e}, {:.15e})", i, x, y);
    }

    // Tight curve
    let pts = flatten_cubic(
        Vec2::new(0.0, 0.0),
        Vec2::new(0.0, 2.0),
        Vec2::new(2.0, 2.0),
        Vec2::new(2.0, 0.0),
        0.01,
    );
    println!("  tight_curve (tol=0.01): {} points", pts.len());
    for (i, (x, y)) in pts.iter().enumerate() {
        println!("    [{:2}] ({:.15e}, {:.15e})", i, x, y);
    }

    // Straight line
    let pts = flatten_cubic(
        Vec2::new(0.0, 0.0),
        Vec2::new(1.0, 0.0),
        Vec2::new(2.0, 0.0),
        Vec2::new(3.0, 0.0),
        0.25,
    );
    println!("  straight_line (tol=0.25): {} points", pts.len());
    for (i, (x, y)) in pts.iter().enumerate() {
        println!("    [{:2}] ({:.15e}, {:.15e})", i, x, y);
    }

    // Cusp
    let pts = flatten_cubic(
        Vec2::new(0.0, 0.0),
        Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0),
        Vec2::new(1.0, 0.0),
        0.1,
    );
    println!("  cusp (tol=0.1): {} points", pts.len());
    for (i, (x, y)) in pts.iter().enumerate() {
        println!("    [{:2}] ({:.15e}, {:.15e})", i, x, y);
    }
}
