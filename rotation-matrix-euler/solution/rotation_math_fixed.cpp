
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

    // Handle antipodal quaternions - always take shortest arc
    if (cosom < 0.0) {
        cosom = -cosom;
        to1 = -to;
    } else {
        to1 = to;
    }

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
    // Project quaternion's vector part onto twist axis
    Vec3 qv(x, y, z);
    double projection = qv.dot(twist_axis);

    // Twist quaternion: keep only the component along twist_axis
    out_twist = Quat(
        twist_axis.x * projection,
        twist_axis.y * projection,
        twist_axis.z * projection,
        w
    );

    double twist_len = out_twist.length();
    if (twist_len < MathUtil::CMP_EPSILON) {
        // The rotation is 180 degrees about an axis perpendicular to twist_axis
        out_twist = Quat(); // identity
    } else {
        out_twist = Quat(out_twist.x / twist_len, out_twist.y / twist_len,
                         out_twist.z / twist_len, out_twist.w / twist_len);
    }

    // Swing = this * twist^(-1)
    out_swing = *this * out_twist.inverse();
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
        case EulerOrder::XZY:
            *this = xmat * zmat * ymat;
            break;
        case EulerOrder::YXZ:
            *this = ymat * xmat * zmat;
            break;
        case EulerOrder::YZX:
            *this = ymat * zmat * xmat;
            break;
        case EulerOrder::ZXY:
            *this = zmat * xmat * ymat;
            break;
        case EulerOrder::ZYX:
            *this = zmat * ymat * xmat;
            break;
        default:
            break;
    }
}

Vec3 Mat3::get_euler(EulerOrder order) const {
    const double epsilon = 0.00000025;

    switch (order) {
        case EulerOrder::XYZ: {
            // rot =  cy*cz          -cy*sz           sy
            //        cz*sx*sy+cx*sz  cx*cz-sx*sy*sz -cy*sx
            //       -cx*cz*sy+sx*sz  cz*sx+cx*sy*sz  cx*cy
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
                        euler.z = std::atan2(-rows[0][1], rows[0][0]);
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
        case EulerOrder::XZY: {
            // rot =  cz*cy             -sz             cz*sy
            //        sx*sy+cx*cy*sz    cx*cz           cx*sz*sy-cy*sx
            //        cy*sx*sz-cx*sy    cz*sx           cx*cy+sx*sz*sy
            Vec3 euler;
            double sz = rows[0][1];
            if (sz < (1.0 - epsilon)) {
                if (sz > -(1.0 - epsilon)) {
                    euler.x = std::atan2(rows[2][1], rows[1][1]);
                    euler.y = std::atan2(rows[0][2], rows[0][0]);
                    euler.z = std::asin(-sz);
                } else {
                    euler.x = -std::atan2(rows[1][2], rows[2][2]);
                    euler.y = 0.0;
                    euler.z = MathUtil::PI / 2.0;
                }
            } else {
                euler.x = -std::atan2(rows[1][2], rows[2][2]);
                euler.y = 0.0;
                euler.z = -MathUtil::PI / 2.0;
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
        case EulerOrder::YZX: {
            // rot =  cy*cz             sy*sx-cy*cx*sz     cx*sy+cy*sz*sx
            //        sz                cz*cx              -cz*sx
            //        -cz*sy            cy*sx+cx*sy*sz     cy*cx-sy*sz*sx
            Vec3 euler;
            double sz = rows[1][0];
            if (sz < (1.0 - epsilon)) {
                if (sz > -(1.0 - epsilon)) {
                    euler.x = std::atan2(-rows[1][2], rows[1][1]);
                    euler.y = std::atan2(-rows[2][0], rows[0][0]);
                    euler.z = std::asin(sz);
                } else {
                    euler.x = std::atan2(rows[2][1], rows[2][2]);
                    euler.y = 0.0;
                    euler.z = -MathUtil::PI / 2.0;
                }
            } else {
                euler.x = std::atan2(rows[2][1], rows[2][2]);
                euler.y = 0.0;
                euler.z = MathUtil::PI / 2.0;
            }
            return euler;
        }
        case EulerOrder::ZXY: {
            // rot =  cz*cy-sz*sx*sy    -cx*sz                cz*sy+cy*sz*sx
            //        cy*sz+cz*sx*sy    cz*cx                 sz*sy-cz*cy*sx
            //        -cx*sy            sx                    cx*cy
            Vec3 euler;
            double sx = rows[2][1];
            if (sx < (1.0 - epsilon)) {
                if (sx > -(1.0 - epsilon)) {
                    euler.x = std::asin(sx);
                    euler.y = std::atan2(-rows[2][0], rows[2][2]);
                    euler.z = std::atan2(-rows[0][1], rows[1][1]);
                } else {
                    euler.x = -MathUtil::PI / 2.0;
                    euler.y = std::atan2(rows[0][2], rows[0][0]);
                    euler.z = 0;
                }
            } else {
                euler.x = MathUtil::PI / 2.0;
                euler.y = std::atan2(rows[0][2], rows[0][0]);
                euler.z = 0;
            }
            return euler;
        }
        case EulerOrder::ZYX: {
            // rot =  cz*cy             cz*sy*sx-cx*sz        sz*sx+cz*cx*sy
            //        cy*sz             cz*cx+sz*sy*sx        cx*sz*sy-cz*sx
            //        -sy               cy*sx                 cy*cx
            Vec3 euler;
            double sy = rows[2][0];
            if (sy < (1.0 - epsilon)) {
                if (sy > -(1.0 - epsilon)) {
                    euler.x = std::atan2(rows[2][1], rows[2][2]);
                    euler.y = std::asin(-sy);
                    euler.z = std::atan2(rows[1][0], rows[0][0]);
                } else {
                    euler.x = 0;
                    euler.y = MathUtil::PI / 2.0;
                    euler.z = -std::atan2(rows[0][1], rows[1][1]);
                }
            } else {
                euler.x = 0;
                euler.y = -MathUtil::PI / 2.0;
                euler.z = -std::atan2(rows[0][1], rows[1][1]);
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

        temp[3] = (rows[k][j] - rows[j][k]) * s;
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

        // 180-degree singularity: matrix is symmetric, angle = PI
        double xx = (rows[0][0] + 1.0) / 2.0;
        double yy = (rows[1][1] + 1.0) / 2.0;
        double zz = (rows[2][2] + 1.0) / 2.0;
        double xy = (rows[0][1] + rows[1][0]) / 4.0;
        double xz = (rows[0][2] + rows[2][0]) / 4.0;
        double yz = (rows[1][2] + rows[2][1]) / 4.0;

        if ((xx > yy) && (xx > zz)) {
            if (xx < MathUtil::CMP_EPSILON) {
                r_axis = Vec3(0, MathUtil::SQRT12, MathUtil::SQRT12);
            } else {
                double x_val = std::sqrt(xx);
                r_axis = Vec3(x_val, xy / x_val, xz / x_val);
            }
        } else if (yy > zz) {
            if (yy < MathUtil::CMP_EPSILON) {
                r_axis = Vec3(MathUtil::SQRT12, 0, MathUtil::SQRT12);
            } else {
                double y_val = std::sqrt(yy);
                r_axis = Vec3(xy / y_val, y_val, yz / y_val);
            }
        } else {
            if (zz < MathUtil::CMP_EPSILON) {
                r_axis = Vec3(MathUtil::SQRT12, MathUtil::SQRT12, 0);
            } else {
                double z_val = std::sqrt(zz);
                r_axis = Vec3(xz / z_val, yz / z_val, z_val);
            }
        }
        r_angle = MathUtil::PI;
        return;
    }

    // General case
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
           MathUtil::is_equal_approx(x_len_sq, z.length_squared()) &&
           MathUtil::is_zero_approx(x.dot(y)) &&
           MathUtil::is_zero_approx(x.dot(z)) &&
           MathUtil::is_zero_approx(y.dot(z));
}

bool Mat3::is_rotation() const {
    return is_conformal() && MathUtil::is_equal_approx(determinant(), 1.0, MathUtil::UNIT_EPSILON);
}

Vec3 Mat3::log_rotation() const {
    double trace_val = rows[0][0] + rows[1][1] + rows[2][2];
    double cos_angle = (trace_val - 1.0) / 2.0;
    // Clamp for numerical safety
    if (cos_angle > 1.0) cos_angle = 1.0;
    if (cos_angle < -1.0) cos_angle = -1.0;
    double angle = std::acos(cos_angle);

    if (angle < MathUtil::CMP_EPSILON) {
        // Near identity: first-order approximation R ≈ I + [omega]_x
        return Vec3(
            (rows[2][1] - rows[1][2]) * 0.5,
            (rows[0][2] - rows[2][0]) * 0.5,
            (rows[1][0] - rows[0][1]) * 0.5
        );
    }

    if (angle > MathUtil::PI - MathUtil::CMP_EPSILON) {
        // Near 180 degrees: extract axis from diagonal
        double xx = (rows[0][0] + 1.0) / 2.0;
        double yy = (rows[1][1] + 1.0) / 2.0;
        double zz = (rows[2][2] + 1.0) / 2.0;
        Vec3 axis;
        if ((xx > yy) && (xx > zz)) {
            if (xx < MathUtil::CMP_EPSILON) {
                axis = Vec3(0, MathUtil::SQRT12, MathUtil::SQRT12);
            } else {
                double x_val = std::sqrt(std::max(xx, 0.0));
                double xy = (rows[0][1] + rows[1][0]) / 4.0;
                double xz = (rows[0][2] + rows[2][0]) / 4.0;
                axis = Vec3(x_val, xy / x_val, xz / x_val);
            }
        } else if (yy > zz) {
            if (yy < MathUtil::CMP_EPSILON) {
                axis = Vec3(MathUtil::SQRT12, 0, MathUtil::SQRT12);
            } else {
                double y_val = std::sqrt(std::max(yy, 0.0));
                double xy = (rows[0][1] + rows[1][0]) / 4.0;
                double yz = (rows[1][2] + rows[2][1]) / 4.0;
                axis = Vec3(xy / y_val, y_val, yz / y_val);
            }
        } else {
            if (zz < MathUtil::CMP_EPSILON) {
                axis = Vec3(MathUtil::SQRT12, MathUtil::SQRT12, 0);
            } else {
                double z_val = std::sqrt(std::max(zz, 0.0));
                double xz = (rows[0][2] + rows[2][0]) / 4.0;
                double yz = (rows[1][2] + rows[2][1]) / 4.0;
                axis = Vec3(xz / z_val, yz / z_val, z_val);
            }
        }
        axis.normalize();
        return axis * MathUtil::PI;
    }

    // General case: theta / (2 * sin(theta)) * (R - R^T)
    double factor = angle / (2.0 * std::sin(angle));
    return Vec3(
        (rows[2][1] - rows[1][2]) * factor,
        (rows[0][2] - rows[2][0]) * factor,
        (rows[1][0] - rows[0][1]) * factor
    );
}

double Mat3::geodesic_distance(const Mat3& other) const {
    Mat3 relative = this->transposed() * other;
    double trace_val = relative.rows[0][0] + relative.rows[1][1] + relative.rows[2][2];
    double cos_angle = (trace_val - 1.0) / 2.0;
    if (cos_angle > 1.0) cos_angle = 1.0;
    if (cos_angle < -1.0) cos_angle = -1.0;
    return std::acos(cos_angle);
}
