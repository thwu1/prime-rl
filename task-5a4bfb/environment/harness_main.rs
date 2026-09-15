// Endomorphism reference harness for the k256 crate.
//
// Build:  cargo build --release
// Run:    cargo run --release
//

use k256::ProjectivePoint;
use k256::Scalar;
use k256::elliptic_curve::sec1::ToEncodedPoint;

fn hex_coords(point: &ProjectivePoint) -> (String, String) {
    let affine = point.to_affine();
    let enc = affine.to_encoded_point(false);
    let x = hex::encode(enc.x());
    let y = hex::encode(enc.y().expect("uncompressed point must have y"));
    (x, y)
}

fn main() {
    println!("=== secp256k1 endomorphism reference data ===");
    println!();

    let g = ProjectivePoint::GENERATOR;

    let (gx, gy) = hex_coords(&g);
    println!("G.x = {}", gx);
    println!("G.y = {}", gy);
    println!();

    let endo_g = g.endomorphism();
    let (ex, ey) = hex_coords(&endo_g);
    println!("endo(G).x = {}", ex);
    println!("endo(G).y = {}", ey);
    println!();

    // Show the endomorphism applied to several multiples of G
    for &k in &[2u64, 7, 42, 1337, 65537] {
        let scalar = Scalar::from(k);
        let p = g * scalar;
        let ep = p.endomorphism();

        let (px, py) = hex_coords(&p);
        let (epx, epy) = hex_coords(&ep);

        println!("--- k = {} ---", k);
        println!("(k*G).x     = {}", px);
        println!("(k*G).y     = {}", py);
        println!("endo(k*G).x = {}", epx);
        println!("endo(k*G).y = {}", epy);
        println!();
    }

    // Verify the endomorphism has order 3
    let test = g * Scalar::from(13u64);
    let e1 = test.endomorphism();
    let e2 = e1.endomorphism();
    let e3 = e2.endomorphism();
    println!("=== order check ===");
    println!("endo^3(P) == P: {}", e3 == test);
    println!("endo^1(P) == P: {}", e1 == test);
    println!("endo^2(P) == P: {}", e2 == test);
}
