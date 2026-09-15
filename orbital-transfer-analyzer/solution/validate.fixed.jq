# Schema validation for orbital mechanics results
# Verifies that results.json contains all required missions with correct field structure

def check_rv2coe: has("p_km") and has("ecc") and has("inc_deg") and has("raan_deg") and has("argp_deg") and has("nu_deg");
def check_coe2rv: has("r_km") and has("v_km_s") and (.r_km | length == 3) and (.v_km_s | length == 3);
def check_lambert: has("v0_km_s") and has("v_km_s") and (.v0_km_s | length == 3) and (.v_km_s | length == 3);
def check_hohmann: has("dv_a_km_s") and has("dv_b_km_s") and has("dv_total_km_s") and has("t_trans_s");
def check_bielliptic: has("dv_a_km_s") and has("dv_b_km_s") and has("dv_c_km_s") and has("dv_total_km_s") and has("t_trans1_s") and has("t_trans2_s");
def check_j2: has("delta_t_s") and has("delta_v_km_s");
def check_plane: has("dv_km_s");
def check_budget: has("dv_depart_total_km_s") and has("dv_arrive_total_km_s") and has("optimal_strategy") and has("dv_optimal_km_s");

has("rv2coe_1") and has("coe2rv_1") and has("lambert_1") and has("lambert_2") and has("hohmann_1") and has("bielliptic_1") and has("j2_correction_1") and has("plane_change_1") and has("mission_budget_1")
and (.rv2coe_1 | check_rv2coe)
and (.coe2rv_1 | check_coe2rv)
and (.lambert_1 | check_lambert)
and (.lambert_2 | check_lambert)
and (.hohmann_1 | check_hohmann)
and (.bielliptic_1 | check_bielliptic)
and (.j2_correction_1 | check_j2)
and (.plane_change_1 | check_plane)
and (.mission_budget_1 | check_budget)
