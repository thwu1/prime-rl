
use pcsaft::*;
use std::fs;

fn main() {
    let propane = PcSaftParams::propane();

    // ======================================================================
    // 1. Helmholtz energy contributions at reference state
    //    T = 250 K, V = 1000 A^3, N = 1 particle  =>  rho = 0.001 A^{-3}
    // ======================================================================
    let t_ref = 250.0;
    let v_ref = 1000.0;
    let rho_ref = 1.0 / v_ref;

    let a_hs = a_hard_sphere(t_ref, rho_ref, &propane) * v_ref;
    let a_hc = a_hard_chain(t_ref, rho_ref, &propane) * v_ref;
    let a_disp = a_dispersion(t_ref, rho_ref, &propane) * v_ref;

    eprintln!("=== Helmholtz energy contributions (x V) at T=250, V=1000, N=1 ===");
    eprintln!("  Hard sphere : {:.12}", a_hs);
    eprintln!("  Hard chain  : {:.12}", a_hc);
    eprintln!("  Dispersion  : {:.12}", a_disp);
    eprintln!("  Total       : {:.12}", a_hs + a_hc + a_disp);

    // ======================================================================
    // 2. Critical point of propane
    // ======================================================================
    let (tc, rhoc) = critical_point(&propane);
    let rhoc_mol_m3 = rhoc * 1e30 / NA;

    eprintln!("\n=== Critical point ===");
    eprintln!("  Tc   = {:.6} K", tc);
    eprintln!("  rhoc = {:.6} mol/m^3", rhoc_mol_m3);

    // ======================================================================
    // 3. Vapor-liquid equilibrium at T = 300 K
    // ======================================================================
    let (_, rho_v, rho_l) = vapor_pressure(300.0, &propane)
        .expect("VLE should exist for propane at 300 K");

    let p_v = pressure_reduced(300.0, rho_v, &propane);
    let p_l = pressure_reduced(300.0, rho_l, &propane);
    let psat_ratio = p_v / p_l;

    let mu_v = chemical_potential_res(300.0, rho_v, &propane) + rho_v.ln();
    let mu_l = chemical_potential_res(300.0, rho_l, &propane) + rho_l.ln();
    let fugacity_diff = (mu_v - mu_l).abs();

    eprintln!("\n=== VLE at T = 300 K ===");
    eprintln!("  rho_v     = {:.10e} 1/A^3", rho_v);
    eprintln!("  rho_l     = {:.10e} 1/A^3", rho_l);
    eprintln!("  P_v / P_l = {:.15}", psat_ratio);
    eprintln!("  |dmu|     = {:.10e}", fugacity_diff);

    // ======================================================================
    // Write results to JSON
    // ======================================================================
    let json = format!(
        "{{\n  \"a_hs_x_v\": {:.15e},\n  \"a_hc_x_v\": {:.15e},\n  \"a_disp_x_v\": {:.15e},\n  \"tc_kelvin\": {:.15e},\n  \"rhoc_mol_m3\": {:.15e},\n  \"psat_ratio\": {:.15e},\n  \"fugacity_diff\": {:.15e}\n}}",
        a_hs, a_hc, a_disp, tc, rhoc_mol_m3, psat_ratio, fugacity_diff
    );

    fs::write("/app/results.json", &json).expect("Failed to write results.json");
    eprintln!("\nResults written to /app/results.json");
}
