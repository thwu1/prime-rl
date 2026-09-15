
#include "rotation_math.hpp"

// ============================================================
// Quat implementations
// ============================================================

Quat Quat::from_euler(const Vec3& euler) {
    double half_y = euler.y * 0.5;
    double half_x = euler.x * 0.5;
    double half_z = euler.z * 0.5;

    double cy = std::cos(half_y), sy = std::sin(half_y);
    double cx = std::cos(half_x), sx = std::sin(half_x);
    double cz = std::cos(half_z), sz = std::sin(half_z);

    return Quat(
        sy * cx * sz + cy * sx * cz,
        sy * cx * cz - cy * sx * sz,
        -sy * sx * cz + cy * cx * sz,
        sy * sx * sz + cy * cx * cz
    );
}

Vec3 Quat::get_euler(EulerOrder order) const {
    return Mat3(*this).get_euler(order);
}

Quat Quat::slerp(const Quat& to, double weight) const {
    Quat to1;
    double cosom = dot(to);

    to1 = to;

    double scale0, scale1;
    if ((1.0 - cosom) > MathUtil::CMP_EPSILON) {
        double omega = MathUtil::safe_acos(cosom);
        double sinom = std::sin(omega);
        scale0 = std::sin((1.0 - weight) * omega) / sinom;
        scale1 = std::sin(weight * omega) / sinom;
    } else {
        scale0 = 1.0 - weight;
        scale1 = weight;
    }

    return Quat(
        scale0 * x + scale1 * to1.x,
        scale0 * y + scale1 * to1.y,
        scale0 * z + scale1 * to1.z,
        scale0 * w + scale1 * to1.w
    );
}

void Quat::swing_twist_decompose(const Vec3& twist_axis, Quat& out_swing, Quat& out_twist) const {
    out_swing = Quat();
    out_twist = Quat();
}

// ============================================================
// Mat3 implementations
// ============================================================

void Mat3::set_euler(const Vec3& euler, EulerOrder order) {
    double c, s;

    c = std::cos(euler.x); s = std::sin(euler.x);
    Mat3 xmat(1, 0, 0, 0, c, -s, 0, s, c);

    c = std::cos(euler.y); s = std::sin(euler.y);
    Mat3 ymat(c, 0, s, 0, 1, 0, -s, 0, c);

    c = std::cos(euler.z); s = std::sin(euler.z);
    Mat3 zmat(c, -s, 0, s, c, 0, 0, 0, 1);

    switch (order) {
        case EulerOrder::XYZ:
            *this = xmat * (ymat * zmat);
            break;
        case EulerOrder::YXZ:
            *this = ymat * xmat * zmat;
            break;
        case EulerOrder::XZY:
        case EulerOrder::YZX:
        case EulerOrder::ZXY:
        case EulerOrder::ZYX:
            break;
        default:
            break;
    }
}

Vec3 Mat3::get_euler(EulerOrder order) const {
    const double epsilon = 0.00000025;

    switch (order) {
        case EulerOrder::XYZ: {
            Vec3 euler;
            double sy = rows[0][2];
            if (sy < (1.0 - epsilon)) {
                if (sy > -(1.0 - epsilon)) {
                    if (rows[1][0] == 0 && rows[0][1] == 0 && rows[1][2] == 0 &&
                        rows[2][1] == 0 && rows[1][1] == 1) {
                        euler.x = 0;
                        euler.y = std::atan2(rows[0][2], rows[0][0]);
                        euler.z = 0;
                    } else {
                        euler.x = std::atan2(-rows[1][2], rows[2][2]);
                        euler.y = std::asin(sy);
                        euler.z = std::atan2(rows[0][1], rows[0][0]);
                    }
                } else {
                    euler.x = std::atan2(rows[2][1], rows[1][1]);
                    euler.y = -MathUtil::PI / 2.0;
                    euler.z = 0.0;
                }
            } else {
                euler.x = std::atan2(rows[2][1], rows[1][1]);
                euler.y = MathUtil::PI / 2.0;
                euler.z = 0.0;
            }
            return euler;
        }
        case EulerOrder::YXZ: {
            Vec3 euler;
            double m12 = rows[1][2];
            if (m12 < (1.0 - epsilon)) {
                if (m12 > -(1.0 - epsilon)) {
                    if (rows[1][0] == 0 && rows[0][1] == 0 && rows[0][2] == 0 &&
                        rows[2][0] == 0 && rows[0][0] == 1) {
                        euler.x = std::atan2(-m12, rows[1][1]);
                        euler.y = 0;
                        euler.z = 0;
                    } else {
                        euler.x = std::asin(-m12);
                        euler.y = std::atan2(rows[0][2], rows[2][2]);
                        euler.z = std::atan2(rows[1][0], rows[1][1]);
                    }
                } else {
                    euler.x = MathUtil::PI * 0.5;
                    euler.y = std::atan2(rows[0][1], rows[0][0]);
                    euler.z = 0;
                }
            } else {
                euler.x = -MathUtil::PI * 0.5;
                euler.y = -std::atan2(rows[0][1], rows[0][0]);
                euler.z = 0;
            }
            return euler;
        }
        default:
            return Vec3(0, 0, 0);
    }
}

Quat Mat3::get_quaternion() const {
    double trace = rows[0][0] + rows[1][1] + rows[2][2];
    double temp[4];

    if (trace > 0.0) {
        double s = std::sqrt(trace + 1.0);
        temp[3] = s * 0.5;
        s = 0.5 / s;

        temp[0] = (rows[2][1] - rows[1][2]) * s;
        temp[1] = (rows[0][2] - rows[2][0]) * s;
        temp[2] = (rows[1][0] - rows[0][1]) * s;
    } else {
        int i = rows[0][0] < rows[1][1]
                ? (rows[1][1] < rows[2][2] ? 2 : 1)
                : (rows[0][0] < rows[2][2] ? 2 : 0);
        int j = (i + 1) % 3;
        int k = (i + 2) % 3;

        double s = std::sqrt(rows[i][i] - rows[j][j] - rows[k][k] + 1.0);
        temp[i] = s * 0.5;
        s = 0.5 / s;

        temp[3] = (rows[k][j] + rows[j][k]) * s;
        temp[j] = (rows[j][i] + rows[i][j]) * s;
        temp[k] = (rows[k][i] + rows[i][k]) * s;
    }

    return Quat(temp[0], temp[1], temp[2], temp[3]);
}

void Mat3::get_axis_angle(Vec3& r_axis, double& r_angle) const {
    if (MathUtil::is_zero_approx(rows[0][1] - rows[1][0]) &&
        MathUtil::is_zero_approx(rows[0][2] - rows[2][0]) &&
        MathUtil::is_zero_approx(rows[1][2] - rows[2][1])) {

        if (is_diagonal() && (std::abs(rows[0][0] + rows[1][1] + rows[2][2] - 3) < 3 * MathUtil::CMP_EPSILON)) {
            r_axis = Vec3(0, 1, 0);
            r_angle = 0;
            return;
        }
    }

    double s = std::sqrt(
        (rows[2][1] - rows[1][2]) * (rows[2][1] - rows[1][2]) +
        (rows[0][2] - rows[2][0]) * (rows[0][2] - rows[2][0]) +
        (rows[1][0] - rows[0][1]) * (rows[1][0] - rows[0][1])
    );

    if (std::abs(s) < MathUtil::CMP_EPSILON) {
        s = 1;
    }

    r_axis.x = (rows[2][1] - rows[1][2]) / s;
    r_axis.y = (rows[0][2] - rows[2][0]) / s;
    r_axis.z = (rows[1][0] - rows[0][1]) / s;

    r_angle = MathUtil::safe_acos((rows[0][0] + rows[1][1] + rows[2][2] - 1.0) / 2.0);
}

bool Mat3::is_orthogonal() const {
    const Vec3 x = get_column(0);
    const Vec3 y = get_column(1);
    const Vec3 z = get_column(2);
    return MathUtil::is_zero_approx(x.dot(y)) &&
           MathUtil::is_zero_approx(x.dot(z)) &&
           MathUtil::is_zero_approx(y.dot(z));
}

bool Mat3::is_orthonormal() const {
    const Vec3 x = get_column(0);
    const Vec3 y = get_column(1);
    const Vec3 z = get_column(2);
    return MathUtil::is_equal_approx(x.length_squared(), 1.0) &&
           MathUtil::is_equal_approx(y.length_squared(), 1.0) &&
           MathUtil::is_equal_approx(z.length_squared(), 1.0) &&
           MathUtil::is_zero_approx(x.dot(y)) &&
           MathUtil::is_zero_approx(x.dot(z)) &&
           MathUtil::is_zero_approx(y.dot(z));
}

bool Mat3::is_conformal() const {
    const Vec3 x = get_column(0);
    const Vec3 y = get_column(1);
    const Vec3 z = get_column(2);
    double x_len_sq = x.length_squared();
    return MathUtil::is_equal_approx(x_len_sq, y.length_squared()) &&
           MathUtil::is_zero_approx(x.dot(y)) &&
           MathUtil::is_zero_approx(x.dot(z)) &&
           MathUtil::is_zero_approx(y.dot(z));
}

bool Mat3::is_rotation() const {
    return is_conformal() && MathUtil::is_equal_approx(determinant(), 1.0, MathUtil::UNIT_EPSILON);
}

Vec3 Mat3::log_rotation() const {
    return Vec3(0, 0, 0);
}

double Mat3::geodesic_distance(const Mat3& other) const {
    return 0.0;
}
