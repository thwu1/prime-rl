//
// Comprehensive test suite for rotation_math library.

#include "rotation_math.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>

static int total_tests = 0;
static int passed_tests = 0;
static int failed_tests = 0;

static void report(const char* name, bool pass, const char* detail = nullptr) {
    total_tests++;
    if (pass) {
        passed_tests++;
        printf("TEST %s PASS\n", name);
    } else {
        failed_tests++;
        if (detail)
            printf("TEST %s FAIL %s\n", name, detail);
        else
            printf("TEST %s FAIL\n", name);
    }
}

static Vec3 deg_to_rad_v(const Vec3& v) {
    return Vec3(MathUtil::deg_to_rad(v.x), MathUtil::deg_to_rad(v.y), MathUtil::deg_to_rad(v.z));
}

static const char* order_name(EulerOrder o) {
    switch (o) {
        case EulerOrder::XYZ: return "XYZ";
        case EulerOrder::XZY: return "XZY";
        case EulerOrder::YXZ: return "YXZ";
        case EulerOrder::YZX: return "YZX";
        case EulerOrder::ZXY: return "ZXY";
        case EulerOrder::ZYX: return "ZYX";
        default: return "???";
    }
}

static bool is_approx_identity(const Mat3& m) {
    Vec3 c0 = m.get_column(0);
    Vec3 c1 = m.get_column(1);
    Vec3 c2 = m.get_column(2);
    return (c0 - Vec3(1,0,0)).length() < 0.002 &&
           (c1 - Vec3(0,1,0)).length() < 0.002 &&
           (c2 - Vec3(0,0,1)).length() < 0.002;
}

// ============================================================
// Test: set_euler produces non-identity for non-trivial angles
// ============================================================
void test_set_euler_nontrivial() {
    Vec3 euler = deg_to_rad_v(Vec3(30, 45, 60));
    Mat3 identity;

    EulerOrder orders[] = {
        EulerOrder::XYZ, EulerOrder::XZY, EulerOrder::YXZ,
        EulerOrder::YZX, EulerOrder::ZXY, EulerOrder::ZYX
    };

    for (int i = 0; i < 6; i++) {
        Mat3 m = Mat3::from_euler(euler, orders[i]);
        char name[64];
        snprintf(name, sizeof(name), "set_euler_nontrivial_%s", order_name(orders[i]));
        report(name, !m.is_equal_approx(identity));
    }
}

// ============================================================
// Test: cross-order Euler roundtrip
// ============================================================
void test_euler_cross_roundtrip() {
    Vec3 test_eulers[] = {
        Vec3(30, 45, 60),
        Vec3(-20, 70, -15),
        Vec3(0.5, 50, 20),
        Vec3(89.9, 0, 0),
        Vec3(0, 89.9, 0),
        Vec3(0, 0, 89.9),
    };
    int n_eulers = sizeof(test_eulers) / sizeof(test_eulers[0]);

    EulerOrder orders[] = {
        EulerOrder::XYZ, EulerOrder::XZY, EulerOrder::YXZ,
        EulerOrder::YZX, EulerOrder::ZXY, EulerOrder::ZYX
    };

    for (int oi = 0; oi < 6; oi++) {
        bool all_pass = true;
        char detail[256] = "";
        for (int ei = 0; ei < n_eulers; ei++) {
            Vec3 euler_rad = deg_to_rad_v(test_eulers[ei]);
            Mat3 original = Mat3::from_euler(euler_rad, EulerOrder::YXZ);
            Vec3 extracted = original.get_euler(orders[oi]);
            Mat3 reconstructed = Mat3::from_euler(extracted, orders[oi]);
            Mat3 diff = original.inverse() * reconstructed;
            if (!is_approx_identity(diff)) {
                all_pass = false;
                snprintf(detail, sizeof(detail), "failed for angles (%.1f, %.1f, %.1f)",
                    test_eulers[ei].x, test_eulers[ei].y, test_eulers[ei].z);
                break;
            }
        }
        char name[64];
        snprintf(name, sizeof(name), "euler_cross_roundtrip_%s", order_name(orders[oi]));
        report(name, all_pass, all_pass ? nullptr : detail);
    }
}

// ============================================================
// Test: self-consistent Euler roundtrip for each order
// ============================================================
void test_euler_self_roundtrip() {
    Vec3 test_angles[] = {
        Vec3(0, 0, 0),
        Vec3(0.5, 0.5, 0.5),
        Vec3(-0.5, -0.5, -0.5),
        Vec3(40, 40, 40),
        Vec3(-40, -40, -40),
        Vec3(0, 0, -90), Vec3(0, -90, 0), Vec3(-90, 0, 0),
        Vec3(0, 0, 90),  Vec3(0, 90, 0),  Vec3(90, 0, 0),
        Vec3(0, 0, -30), Vec3(0, -30, 0), Vec3(-30, 0, 0),
        Vec3(0, 0, 30),  Vec3(0, 30, 0),  Vec3(30, 0, 0),
        Vec3(0.5, 50, 20),
        Vec3(-0.5, -50, -20),
        Vec3(0.5, 0, 90), Vec3(0.5, 0, -90),
        Vec3(360, 360, 360), Vec3(-360, -360, -360),
        Vec3(-90, 60, -90), Vec3(90, 60, -90),
        Vec3(90, -60, -90), Vec3(-90, -60, -90),
        Vec3(-90, 60, 90),  Vec3(90, 60, 90),
        Vec3(90, -60, 90),  Vec3(-90, -60, 90),
        Vec3(60, 90, -40),  Vec3(60, -90, -40),
        Vec3(-60, -90, -40), Vec3(-60, 90, 40),
        Vec3(60, 90, 40),   Vec3(60, -90, 40),
        Vec3(-60, -90, 40),
        Vec3(-90, 90, -90),  Vec3(90, 90, -90),
        Vec3(90, -90, -90),  Vec3(-90, -90, -90),
        Vec3(-90, 90, 90),   Vec3(90, 90, 90),
        Vec3(90, -90, 90),
        Vec3(20, 150, 30),   Vec3(20, -150, 30),
        Vec3(-120, -150, 30), Vec3(-120, -150, -130),
        Vec3(120, -150, -130), Vec3(120, 150, -130),
        Vec3(120, 150, 130),
        Vec3(89.9, 0, 0), Vec3(-89.9, 0, 0),
        Vec3(0, 89.9, 0), Vec3(0, -89.9, 0),
        Vec3(0, 0, 89.9), Vec3(0, 0, -89.9),
    };
    int n_angles = sizeof(test_angles) / sizeof(test_angles[0]);

    EulerOrder orders[] = {
        EulerOrder::XYZ, EulerOrder::XZY, EulerOrder::YXZ,
        EulerOrder::YZX, EulerOrder::ZXY, EulerOrder::ZYX
    };

    for (int h = 0; h < 6; h++) {
        bool all_pass = true;
        char detail[256] = "";
        for (int i = 0; i < n_angles; i++) {
            Vec3 original_euler = deg_to_rad_v(test_angles[i]);
            Mat3 to_rotation = Mat3::from_euler(original_euler, orders[h]);
            Vec3 euler_from_rotation = to_rotation.get_euler(orders[h]);
            Mat3 rotation_from_computed = Mat3::from_euler(euler_from_rotation, orders[h]);

            Mat3 res = to_rotation.inverse() * rotation_from_computed;
            if (!is_approx_identity(res)) {
                all_pass = false;
                snprintf(detail, sizeof(detail), "failed for (%.1f, %.1f, %.1f)",
                    test_angles[i].x, test_angles[i].y, test_angles[i].z);
                break;
            }
        }
        char name[64];
        snprintf(name, sizeof(name), "euler_self_roundtrip_%s", order_name(orders[h]));
        report(name, all_pass, all_pass ? nullptr : detail);
    }
}

// ============================================================
// Test: quaternion from matrix roundtrip
// ============================================================
void test_quaternion_from_matrix() {
    Vec3 test_eulers[] = {
        Vec3(0, 0, 0),
        Vec3(30, 0, 0),
        Vec3(0, 45, 0),
        Vec3(0, 0, 60),
        Vec3(30, 45, 60),
        Vec3(120, -30, 45),
        Vec3(-150, 60, -120),
        Vec3(170, 170, 170),
        Vec3(160, -45, 130),
        Vec3(180, 0, 0),
    };
    int n = sizeof(test_eulers) / sizeof(test_eulers[0]);
    bool all_pass = true;
    char detail[256] = "";

    for (int i = 0; i < n; i++) {
        Vec3 euler_rad = deg_to_rad_v(test_eulers[i]);
        Mat3 mat = Mat3::from_euler(euler_rad, EulerOrder::YXZ);

        Quat q = mat.get_quaternion();
        Mat3 mat2;
        mat2.set_quaternion(q);

        Mat3 diff = mat.inverse() * mat2;
        if (!is_approx_identity(diff)) {
            all_pass = false;
            snprintf(detail, sizeof(detail), "failed for euler (%.1f, %.1f, %.1f)",
                test_eulers[i].x, test_eulers[i].y, test_eulers[i].z);
            break;
        }
    }
    report("quaternion_from_matrix_roundtrip", all_pass, all_pass ? nullptr : detail);
}

// ============================================================
// Test: quaternion specific values
// ============================================================
void test_quaternion_values() {
    Quat q(Vec3(1, 0, 0), MathUtil::deg_to_rad(120.0));
    bool ok = std::abs(q.x - 0.866025) < 0.001 &&
              std::abs(q.y) < 0.001 &&
              std::abs(q.z) < 0.001 &&
              std::abs(q.w - 0.5) < 0.001;
    report("quat_axis_angle_120_x", ok);

    q = Quat(Vec3(0, 1, 0), MathUtil::deg_to_rad(30.0));
    ok = std::abs(q.x) < 0.001 &&
         std::abs(q.y - 0.258819) < 0.001 &&
         std::abs(q.z) < 0.001 &&
         std::abs(q.w - 0.965926) < 0.001;
    report("quat_axis_angle_30_y", ok);

    q = Quat(Vec3(0, 0, 1), MathUtil::deg_to_rad(60.0));
    ok = std::abs(q.x) < 0.001 &&
         std::abs(q.y) < 0.001 &&
         std::abs(q.z - 0.5) < 0.001 &&
         std::abs(q.w - 0.866025) < 0.001;
    report("quat_axis_angle_60_z", ok);
}

// ============================================================
// Test: axis-angle extraction
// ============================================================
void test_axis_angle() {
    Vec3 axis;
    double angle;

    Mat3 identity;
    identity.get_axis_angle(axis, angle);
    report("axis_angle_identity", std::abs(angle) < 0.001);

    Mat3 rot180(-1, 0, 0, 0, 1, 0, 0, 0, -1);
    rot180.get_axis_angle(axis, angle);
    bool angle_ok = std::abs(angle - MathUtil::PI) < 0.01 && !MathUtil::is_nan(angle);
    bool axis_ok = axis.length() > 0.5;
    if (axis_ok && angle_ok) {
        Mat3 reconstructed;
        reconstructed.set_axis_angle(axis.normalized(), angle);
        Mat3 diff180 = rot180.inverse() * reconstructed;
        axis_ok = is_approx_identity(diff180);
    }
    bool ok = angle_ok && axis_ok;
    report("axis_angle_180_y", ok, ok ? nullptr : "angle or axis incorrect for 180-degree rotation");

    double cos30 = std::cos(MathUtil::deg_to_rad(30.0));
    Mat3 rot30z(cos30, -0.5, 0, 0.5, cos30, 0, 0, 0, 1);
    rot30z.get_axis_angle(axis, angle);
    ok = std::abs(angle - MathUtil::deg_to_rad(30.0)) < 0.001 &&
         (axis - Vec3(0, 0, 1)).length() < 0.01;
    report("axis_angle_30_z", ok);

    Mat3 rot90x(1, 0, 0, 0, 0, -1, 0, 1, 0);
    rot90x.get_axis_angle(axis, angle);
    ok = std::abs(angle - MathUtil::PI / 2.0) < 0.001 &&
         (axis - Vec3(1, 0, 0)).length() < 0.01;
    report("axis_angle_90_x", ok);

    Mat3 tiny(1, 0, 0, 0, 0.9999995, -0.001, 0, 0.001, 0.9999995);
    tiny.get_axis_angle(axis, angle);
    ok = std::abs(angle - 0.001) < 0.001 && !MathUtil::is_nan(angle);
    report("axis_angle_near_zero", ok);

    Mat3 bugNan(1.00000024, 0, 0.000100001693, 0, 1, 0, -0.000100009143, 0, 1.00000024);
    bugNan.get_axis_angle(axis, angle);
    report("axis_angle_no_nan", !MathUtil::is_nan(angle));
}

// ============================================================
// Test: slerp
// ============================================================
void test_slerp() {
    Quat a(Vec3(1,0,0), MathUtil::deg_to_rad(30.0));
    Quat b(Vec3(0,1,0), MathUtil::deg_to_rad(60.0));

    Quat s0 = a.slerp(b, 0.0);
    report("slerp_t0", s0.is_equal_approx(a));

    Quat s1 = a.slerp(b, 1.0);
    report("slerp_t1", s1.is_equal_approx(b));

    Quat mid = a.slerp(b, 0.5);
    report("slerp_midpoint_normalized", mid.is_normalized());

    Quat neg_b = -b;
    Quat s_neg = a.slerp(neg_b, 0.5);
    Vec3 test_vec(1, 2, 3);
    Vec3 v1 = mid.xform(test_vec);
    Vec3 v2 = s_neg.xform(test_vec);
    report("slerp_antipodal_same_rotation", v1.is_equal_approx(v2));

    Quat self = a.slerp(a, 0.5);
    report("slerp_self", self.is_equal_approx(a));
}

// ============================================================
// Test: property checks
// ============================================================
void test_properties() {
    Mat3 id;
    report("identity_is_conformal", id.is_conformal());
    report("identity_is_orthogonal", id.is_orthogonal());
    report("identity_is_orthonormal", id.is_orthonormal());
    report("identity_is_rotation", id.is_rotation());

    Mat3 rot = Mat3::from_euler(Vec3(1.2, 3.4, 5.6));
    report("rotation_is_conformal", rot.is_conformal());
    report("rotation_is_rotation", rot.is_rotation());

    Mat3 us = Mat3::from_scale(Vec3(1.2, 1.2, 1.2));
    report("uniform_scale_is_conformal", us.is_conformal());
    report("uniform_scale_not_rotation", !us.is_rotation());

    Mat3 nus = Mat3::from_scale(Vec3(1.2, 3.4, 5.6));
    report("nonuniform_scale_not_conformal", !nus.is_conformal());

    Mat3 pus = Mat3::from_scale(Vec3(2, 2, 3));
    report("partial_uniform_not_conformal", !pus.is_conformal());

    Mat3 flip = Mat3::from_scale(Vec3(-1, -1, -1));
    report("flip_is_conformal", flip.is_conformal());
    report("flip_is_orthonormal", flip.is_orthonormal());

    report("scale_is_orthogonal", nus.is_orthogonal());
    report("scale_not_orthonormal", !nus.is_orthonormal());

    Mat3 zero(0,0,0, 0,0,0, 0,0,0);
    report("zero_is_conformal", zero.is_conformal());
}

// ============================================================
// Test: Euler-Quaternion consistency
// ============================================================
void test_euler_quat_consistency() {
    double x = MathUtil::deg_to_rad(30.0);
    double y = MathUtil::deg_to_rad(45.0);
    double z = MathUtil::deg_to_rad(10.0);
    Vec3 euler(x, y, z);

    EulerOrder orders[] = {
        EulerOrder::XYZ, EulerOrder::XZY, EulerOrder::YXZ,
        EulerOrder::YZX, EulerOrder::ZXY, EulerOrder::ZYX
    };

    for (int i = 0; i < 6; i++) {
        Mat3 basis = Mat3::from_euler(euler, orders[i]);
        Quat q = basis.get_quaternion();
        Vec3 check = q.get_euler(orders[i]);

        char name[64];
        snprintf(name, sizeof(name), "euler_quat_consistency_%s", order_name(orders[i]));

        bool euler_ok = check.is_equal_approx(euler);
        bool basis_ok = check.is_equal_approx(basis.get_euler(orders[i]));
        report(name, euler_ok && basis_ok);
    }
}

// ============================================================
// Test: quaternion xform matches matrix xform
// ============================================================
void test_quaternion_xform() {
    Quat q(Vec3(1, 0, 0), MathUtil::deg_to_rad(120.0));
    Vec3 j_t = q.xform(Vec3(0, 1, 0));
    Vec3 k_t = q.xform(Vec3(0, 0, 1));

    report("quat_xform_120x_j", j_t.is_equal_approx(Vec3(0, -0.5, 0.866025)));
    report("quat_xform_120x_k", k_t.is_equal_approx(Vec3(0, -0.866025, -0.5)));

    Vec3 euler(MathUtil::deg_to_rad(31.41), MathUtil::deg_to_rad(-49.16), MathUtil::deg_to_rad(12.34));
    Mat3 basis = Mat3::from_euler(euler);
    Quat q2 = basis.get_quaternion();

    Vec3 v(3, 4, 5);
    Vec3 v_rot = q2.xform(v);
    Vec3 v_compare = basis.xform(v);

    report("quat_xform_matches_matrix", v_rot.is_equal_approx(v_compare));
}

// ============================================================
// Test: quaternion product
// ============================================================
void test_quaternion_product() {
    Quat p(1.0, -2.0, 1.0, 3.0);
    Quat q(-1.0, 2.0, 3.0, 2.0);
    Quat pq = p * q;

    bool ok = std::abs(pq[0] - (-9.0)) < 0.001 &&
              std::abs(pq[1] - (-2.0)) < 0.001 &&
              std::abs(pq[2] - 11.0) < 0.001 &&
              std::abs(pq[3] - 8.0) < 0.001;
    report("quat_product_book", ok);
}

// ============================================================
// Test: log_rotation
// ============================================================
void test_log_rotation() {
    // Identity -> zero vector
    Mat3 id;
    Vec3 log_id = id.log_rotation();
    report("log_rotation_identity", log_id.length() < 0.001);

    // 90 degrees about Z
    Mat3 rot90z;
    rot90z.set_axis_angle(Vec3(0, 0, 1), MathUtil::PI / 2.0);
    Vec3 log_90z = rot90z.log_rotation();
    bool ok = std::abs(log_90z.x) < 0.001 && std::abs(log_90z.y) < 0.001 &&
              std::abs(log_90z.z - MathUtil::PI / 2.0) < 0.001;
    report("log_rotation_90_z", ok);

    // 180 degrees about Y - roundtrip check
    Mat3 rot180;
    rot180.set_axis_angle(Vec3(0, 1, 0), MathUtil::PI);
    Vec3 log_180 = rot180.log_rotation();
    ok = std::abs(log_180.length() - MathUtil::PI) < 0.01 && log_180.is_finite();
    if (log_180.length() > MathUtil::CMP_EPSILON && ok) {
        Mat3 recon180;
        recon180.set_axis_angle(log_180.normalized(), log_180.length());
        Mat3 diff180 = rot180.inverse() * recon180;
        ok = ok && is_approx_identity(diff180);
    }
    report("log_rotation_180", ok);

    // General rotation roundtrip
    Vec3 euler_rad = deg_to_rad_v(Vec3(30, 45, 60));
    Mat3 mat_general = Mat3::from_euler(euler_rad, EulerOrder::YXZ);
    Vec3 log_v = mat_general.log_rotation();
    double angle_v = log_v.length();
    Mat3 reconstructed;
    if (angle_v > MathUtil::CMP_EPSILON) {
        reconstructed.set_axis_angle(log_v.normalized(), angle_v);
    }
    Mat3 diff = mat_general.inverse() * reconstructed;
    report("log_rotation_roundtrip", is_approx_identity(diff));

    // Small angle
    Mat3 small_rot;
    small_rot.set_axis_angle(Vec3(1, 0, 0), 0.001);
    Vec3 log_small = small_rot.log_rotation();
    ok = std::abs(log_small.length() - 0.001) < 0.0001 && log_small.is_finite();
    report("log_rotation_small_angle", ok);

    // No NaN for any test case
    report("log_rotation_no_nan",
           log_id.is_finite() && log_90z.is_finite() && log_180.is_finite() &&
           log_v.is_finite() && log_small.is_finite());
}

// ============================================================
// Test: geodesic_distance
// ============================================================
void test_geodesic_distance() {
    Mat3 id;

    // Distance to self = 0
    report("geodesic_distance_self_zero", std::abs(id.geodesic_distance(id)) < 0.001);

    // Identity to 90-degree rotation = PI/2
    Mat3 rot90;
    rot90.set_axis_angle(Vec3(0, 1, 0), MathUtil::PI / 2.0);
    double d90 = id.geodesic_distance(rot90);
    report("geodesic_distance_90", std::abs(d90 - MathUtil::PI / 2.0) < 0.001);

    // Identity to 180-degree rotation = PI
    Mat3 rot180;
    rot180.set_axis_angle(Vec3(0, 1, 0), MathUtil::PI);
    double d180 = id.geodesic_distance(rot180);
    report("geodesic_distance_180", std::abs(d180 - MathUtil::PI) < 0.01);

    // Symmetry
    Mat3 a = Mat3::from_euler(deg_to_rad_v(Vec3(30, 45, 60)));
    Mat3 b = Mat3::from_euler(deg_to_rad_v(Vec3(-20, 70, -15)));
    double d_ab = a.geodesic_distance(b);
    double d_ba = b.geodesic_distance(a);
    report("geodesic_distance_symmetric", std::abs(d_ab - d_ba) < 0.001);

    // Non-negative
    report("geodesic_distance_nonneg", d90 >= 0 && d180 >= 0 && d_ab >= 0);

    // Triangle inequality
    Mat3 c = Mat3::from_euler(deg_to_rad_v(Vec3(10, 20, 30)));
    double d_ac = a.geodesic_distance(c);
    double d_bc = b.geodesic_distance(c);
    report("geodesic_distance_triangle_ineq", d_ac <= d_ab + d_bc + 0.001);
}

// ============================================================
// Test: swing_twist_decompose
// ============================================================
void test_swing_twist_decompose() {
    Vec3 y_axis(0, 1, 0);
    Quat swing, twist;

    // Pure twist: rotation about Y -> swing = identity
    Quat pure_twist(Vec3(0, 1, 0), MathUtil::deg_to_rad(45.0));
    pure_twist.swing_twist_decompose(y_axis, swing, twist);
    report("swing_twist_pure_twist_swing_id",
           swing.is_equal_approx(Quat()) || swing.is_equal_approx(-Quat()));
    report("swing_twist_pure_twist_match",
           twist.is_equal_approx(pure_twist) || twist.is_equal_approx(-pure_twist));

    // Pure swing: rotation about X (perpendicular to Y) -> twist = identity
    Quat pure_swing(Vec3(1, 0, 0), MathUtil::deg_to_rad(60.0));
    pure_swing.swing_twist_decompose(y_axis, swing, twist);
    report("swing_twist_pure_swing_twist_id",
           twist.is_equal_approx(Quat()) || twist.is_equal_approx(-Quat()));

    // Composition: swing * twist must equal original
    Quat general(Vec3(1, 1, 1).normalized(), MathUtil::deg_to_rad(73.0));
    general.swing_twist_decompose(y_axis, swing, twist);
    Quat composed = swing * twist;
    Vec3 test_vec(3, 4, 5);
    Vec3 v_original = general.xform(test_vec);
    Vec3 v_composed = composed.xform(test_vec);
    report("swing_twist_composition", v_original.is_equal_approx(v_composed));

    // Both normalized
    report("swing_twist_normalized", swing.is_normalized() && twist.is_normalized());

    // Twist axis parallel to twist_axis
    Vec3 twist_vec(twist.x, twist.y, twist.z);
    if (twist_vec.length() > MathUtil::CMP_EPSILON) {
        Vec3 cross_v = twist_vec.cross(y_axis);
        report("swing_twist_axis_parallel", cross_v.length() < 0.001);
    } else {
        report("swing_twist_axis_parallel", true);
    }

    // Swing perpendicular to twist axis
    Vec3 swing_vec(swing.x, swing.y, swing.z);
    if (swing_vec.length() > MathUtil::CMP_EPSILON) {
        double dot_val = std::abs(swing_vec.dot(y_axis));
        report("swing_twist_swing_perp", dot_val < 0.001);
    } else {
        report("swing_twist_swing_perp", true);
    }

    // Different twist axis (Z)
    Vec3 z_axis(0, 0, 1);
    Quat q2(Vec3(1, 2, 3).normalized(), MathUtil::deg_to_rad(120.0));
    q2.swing_twist_decompose(z_axis, swing, twist);
    Quat composed2 = swing * twist;
    v_original = q2.xform(test_vec);
    Vec3 v_composed2 = composed2.xform(test_vec);
    report("swing_twist_z_axis_composition", v_original.is_equal_approx(v_composed2));
}

// ============================================================
// Main
// ============================================================
int main() {
    printf("=== Rotation Math Test Suite ===\n\n");

    test_set_euler_nontrivial();
    test_euler_cross_roundtrip();
    test_euler_self_roundtrip();
    test_quaternion_from_matrix();
    test_quaternion_values();
    test_axis_angle();
    test_slerp();
    test_properties();
    test_euler_quat_consistency();
    test_quaternion_xform();
    test_quaternion_product();
    test_log_rotation();
    test_geodesic_distance();
    test_swing_twist_decompose();

    printf("\n=== SUMMARY: %d/%d tests passed ===\n", passed_tests, total_tests);

    return (failed_tests == 0) ? 0 : 1;
}
