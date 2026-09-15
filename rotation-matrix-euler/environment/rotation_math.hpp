//
// rotation_math.hpp — Self-contained 3D rotation math library
// Provides Vec3, Quat, and Mat3 types for rotation operations.

#pragma once

#include <cmath>
#include <cstdio>
#include <algorithm>
#include <functional>

namespace MathUtil {
    inline constexpr double PI = 3.1415926535897932384626433833;
    inline constexpr double TAU = 6.2831853071795864769252867666;
    inline constexpr double CMP_EPSILON = 0.00001;
    inline constexpr double CMP_EPSILON2 = CMP_EPSILON * CMP_EPSILON;
    inline constexpr double UNIT_EPSILON = 0.001;
    inline constexpr double SQRT12 = 0.7071067811865475244008443621048490;

    inline double deg_to_rad(double d) { return d * (PI / 180.0); }
    inline double rad_to_deg(double r) { return r * (180.0 / PI); }

    inline bool is_zero_approx(double v) { return std::abs(v) < CMP_EPSILON; }
    inline bool is_equal_approx(double a, double b) {
        if (a == b) return true;
        double tol = CMP_EPSILON * std::abs(a);
        if (tol < CMP_EPSILON) tol = CMP_EPSILON;
        return std::abs(a - b) < tol;
    }
    inline bool is_equal_approx(double a, double b, double tol) {
        if (a == b) return true;
        return std::abs(a - b) < tol;
    }
    inline bool is_finite(double v) { return std::isfinite(v); }
    inline bool is_nan(double v) { return std::isnan(v); }

    inline double safe_asin(double x) {
        return x < -1.0 ? (-PI / 2.0) : (x > 1.0 ? (PI / 2.0) : std::asin(x));
    }
    inline double safe_acos(double x) {
        return x < -1.0 ? PI : (x > 1.0 ? 0.0 : std::acos(x));
    }
}

enum class EulerOrder { XYZ = 0, XZY, YXZ, YZX, ZXY, ZYX };

struct Mat3; // forward

struct Vec3 {
    union {
        struct { double x, y, z; };
        double coord[3];
    };

    Vec3() : x(0), y(0), z(0) {}
    Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}

    double& operator[](int i) { return coord[i]; }
    const double& operator[](int i) const { return coord[i]; }

    double dot(const Vec3& v) const { return x*v.x + y*v.y + z*v.z; }
    Vec3 cross(const Vec3& v) const {
        return Vec3(y*v.z - z*v.y, z*v.x - x*v.z, x*v.y - y*v.x);
    }
    double length() const { return std::sqrt(x*x + y*y + z*z); }
    double length_squared() const { return x*x + y*y + z*z; }
    void normalize() {
        double l = length();
        if (l > 0) { x /= l; y /= l; z /= l; }
        else { x = y = z = 0; }
    }
    Vec3 normalized() const { Vec3 v = *this; v.normalize(); return v; }
    bool is_normalized() const { return MathUtil::is_equal_approx(length_squared(), 1.0, MathUtil::UNIT_EPSILON); }
    bool is_finite() const { return MathUtil::is_finite(x) && MathUtil::is_finite(y) && MathUtil::is_finite(z); }
    bool is_zero_approx() const { return MathUtil::is_zero_approx(x) && MathUtil::is_zero_approx(y) && MathUtil::is_zero_approx(z); }
    Vec3 inverse() const { return Vec3(1.0/x, 1.0/y, 1.0/z); }

    Vec3 operator+(const Vec3& v) const { return Vec3(x+v.x, y+v.y, z+v.z); }
    Vec3 operator-(const Vec3& v) const { return Vec3(x-v.x, y-v.y, z-v.z); }
    Vec3 operator*(double s) const { return Vec3(x*s, y*s, z*s); }
    Vec3 operator/(double s) const { return Vec3(x/s, y/s, z/s); }
    Vec3 operator-() const { return Vec3(-x, -y, -z); }
    Vec3 operator*(const Vec3& v) const { return Vec3(x*v.x, y*v.y, z*v.z); }
    Vec3& operator+=(const Vec3& v) { x+=v.x; y+=v.y; z+=v.z; return *this; }
    Vec3& operator-=(const Vec3& v) { x-=v.x; y-=v.y; z-=v.z; return *this; }
    Vec3& operator*=(double s) { x*=s; y*=s; z*=s; return *this; }
    Vec3& operator*=(const Vec3& v) { x*=v.x; y*=v.y; z*=v.z; return *this; }
    Vec3& operator/=(double s) { x/=s; y/=s; z/=s; return *this; }

    bool operator==(const Vec3& v) const { return x == v.x && y == v.y && z == v.z; }
    bool operator!=(const Vec3& v) const { return !(*this == v); }

    bool is_equal_approx(const Vec3& v) const {
        return MathUtil::is_equal_approx(x, v.x) && MathUtil::is_equal_approx(y, v.y) && MathUtil::is_equal_approx(z, v.z);
    }

    Vec3 get_any_perpendicular() const {
        Vec3 up = (std::abs(x) <= std::abs(y) && std::abs(x) <= std::abs(z)) ? Vec3(1,0,0) : Vec3(0,1,0);
        return cross(up).normalized();
    }
};

inline Vec3 operator*(double s, const Vec3& v) { return v * s; }

struct Quat {
    union {
        struct { double x, y, z, w; };
        double components[4];
    };

    Quat() : x(0), y(0), z(0), w(1) {}
    Quat(double x_, double y_, double z_, double w_) : x(x_), y(y_), z(z_), w(w_) {}

    Quat(const Vec3& axis, double angle) {
        double d = axis.length();
        if (d == 0) { x = y = z = 0; w = 0; return; }
        double sin_a = std::sin(angle * 0.5);
        double cos_a = std::cos(angle * 0.5);
        double s = sin_a / d;
        x = axis.x * s;
        y = axis.y * s;
        z = axis.z * s;
        w = cos_a;
    }

    double& operator[](int i) { return components[i]; }
    const double& operator[](int i) const { return components[i]; }

    double length() const { return std::sqrt(x*x + y*y + z*z + w*w); }
    double length_squared() const { return x*x + y*y + z*z + w*w; }
    double dot(const Quat& q) const { return x*q.x + y*q.y + z*q.z + w*q.w; }
    void normalize() { double l = length(); x/=l; y/=l; z/=l; w/=l; }
    Quat normalized() const { double l = length(); return Quat(x/l, y/l, z/l, w/l); }
    bool is_normalized() const { return MathUtil::is_equal_approx(length_squared(), 1.0, MathUtil::UNIT_EPSILON); }
    Quat inverse() const { return Quat(-x, -y, -z, w); }
    bool is_finite() const { return MathUtil::is_finite(x) && MathUtil::is_finite(y) && MathUtil::is_finite(z) && MathUtil::is_finite(w); }

    Quat operator-() const { return Quat(-x, -y, -z, -w); }
    Quat operator*(double s) const { return Quat(x*s, y*s, z*s, w*s); }
    Quat operator+(const Quat& q) const { return Quat(x+q.x, y+q.y, z+q.z, w+q.w); }
    Quat operator-(const Quat& q) const { return Quat(x-q.x, y-q.y, z-q.z, w-q.w); }

    Quat operator*(const Quat& q) const {
        return Quat(
            w * q.x + x * q.w + y * q.z - z * q.y,
            w * q.y + y * q.w + z * q.x - x * q.z,
            w * q.z + z * q.w + x * q.y - y * q.x,
            w * q.w - x * q.x - y * q.y - z * q.z
        );
    }

    Vec3 xform(const Vec3& v) const {
        Vec3 u(x, y, z);
        Vec3 uv = u.cross(v);
        return v + ((uv * w) + u.cross(uv)) * 2.0;
    }

    bool is_equal_approx(const Quat& q) const {
        return MathUtil::is_equal_approx(x, q.x) && MathUtil::is_equal_approx(y, q.y) &&
               MathUtil::is_equal_approx(z, q.z) && MathUtil::is_equal_approx(w, q.w);
    }

    // Implemented in rotation_math.cpp
    static Quat from_euler(const Vec3& euler);
    Vec3 get_euler(EulerOrder order = EulerOrder::YXZ) const;
    Quat slerp(const Quat& to, double weight) const;
    void swing_twist_decompose(const Vec3& twist_axis, Quat& out_swing, Quat& out_twist) const;
};

struct Mat3 {
    // Stored as rows[row][col]. Column vectors represent basis axes.
    // Column i = Vec3(rows[0][i], rows[1][i], rows[2][i])
    Vec3 rows[3];

    Mat3() {
        rows[0] = Vec3(1, 0, 0);
        rows[1] = Vec3(0, 1, 0);
        rows[2] = Vec3(0, 0, 1);
    }

    Mat3(double xx, double xy, double xz,
         double yx, double yy, double yz,
         double zx, double zy, double zz) {
        rows[0] = Vec3(xx, xy, xz);
        rows[1] = Vec3(yx, yy, yz);
        rows[2] = Vec3(zx, zy, zz);
    }

    // Construct from quaternion
    explicit Mat3(const Quat& q) { set_quaternion(q); }

    Vec3 get_column(int i) const {
        return Vec3(rows[0][i], rows[1][i], rows[2][i]);
    }

    void set_column(int i, const Vec3& v) {
        rows[0][i] = v.x;
        rows[1][i] = v.y;
        rows[2][i] = v.z;
    }

    Vec3 get_main_diagonal() const {
        return Vec3(rows[0][0], rows[1][1], rows[2][2]);
    }

    Mat3 transposed() const {
        return Mat3(
            rows[0][0], rows[1][0], rows[2][0],
            rows[0][1], rows[1][1], rows[2][1],
            rows[0][2], rows[1][2], rows[2][2]
        );
    }

    double determinant() const {
        return rows[0][0] * (rows[1][1] * rows[2][2] - rows[2][1] * rows[1][2]) -
               rows[1][0] * (rows[0][1] * rows[2][2] - rows[2][1] * rows[0][2]) +
               rows[2][0] * (rows[0][1] * rows[1][2] - rows[1][1] * rows[0][2]);
    }

    Mat3 inverse() const {
        double co0 = rows[1][1]*rows[2][2] - rows[1][2]*rows[2][1];
        double co1 = rows[1][2]*rows[2][0] - rows[1][0]*rows[2][2];
        double co2 = rows[1][0]*rows[2][1] - rows[1][1]*rows[2][0];
        double det = rows[0][0]*co0 + rows[0][1]*co1 + rows[0][2]*co2;
        double s = 1.0 / det;
        return Mat3(
            co0*s, (rows[0][2]*rows[2][1] - rows[0][1]*rows[2][2])*s, (rows[0][1]*rows[1][2] - rows[0][2]*rows[1][1])*s,
            co1*s, (rows[0][0]*rows[2][2] - rows[0][2]*rows[2][0])*s, (rows[0][2]*rows[1][0] - rows[0][0]*rows[1][2])*s,
            co2*s, (rows[0][1]*rows[2][0] - rows[0][0]*rows[2][1])*s, (rows[0][0]*rows[1][1] - rows[0][1]*rows[1][0])*s
        );
    }

    Vec3 xform(const Vec3& v) const {
        return Vec3(rows[0].dot(v), rows[1].dot(v), rows[2].dot(v));
    }

    double tdotx(const Vec3& v) const { return rows[0][0]*v[0] + rows[1][0]*v[1] + rows[2][0]*v[2]; }
    double tdoty(const Vec3& v) const { return rows[0][1]*v[0] + rows[1][1]*v[1] + rows[2][1]*v[2]; }
    double tdotz(const Vec3& v) const { return rows[0][2]*v[0] + rows[1][2]*v[1] + rows[2][2]*v[2]; }

    Mat3 operator*(const Mat3& m) const {
        return Mat3(
            m.tdotx(rows[0]), m.tdoty(rows[0]), m.tdotz(rows[0]),
            m.tdotx(rows[1]), m.tdoty(rows[1]), m.tdotz(rows[1]),
            m.tdotx(rows[2]), m.tdoty(rows[2]), m.tdotz(rows[2])
        );
    }

    void scale(const Vec3& s) {
        rows[0] *= s.x;
        rows[1] *= s.y;
        rows[2] *= s.z;
    }

    Mat3 scaled(const Vec3& s) const {
        Mat3 m = *this;
        m.scale(s);
        return m;
    }

    static Mat3 from_scale(const Vec3& s) {
        return Mat3(s.x, 0, 0, 0, s.y, 0, 0, 0, s.z);
    }

    Vec3 get_scale_abs() const {
        return Vec3(
            Vec3(rows[0][0], rows[1][0], rows[2][0]).length(),
            Vec3(rows[0][1], rows[1][1], rows[2][1]).length(),
            Vec3(rows[0][2], rows[1][2], rows[2][2]).length()
        );
    }

    bool is_equal_approx(const Mat3& m) const {
        return rows[0].is_equal_approx(m.rows[0]) && rows[1].is_equal_approx(m.rows[1]) && rows[2].is_equal_approx(m.rows[2]);
    }

    bool is_finite() const {
        return rows[0].is_finite() && rows[1].is_finite() && rows[2].is_finite();
    }

    bool is_diagonal() const {
        return MathUtil::is_zero_approx(rows[0][1]) && MathUtil::is_zero_approx(rows[0][2]) &&
               MathUtil::is_zero_approx(rows[1][0]) && MathUtil::is_zero_approx(rows[1][2]) &&
               MathUtil::is_zero_approx(rows[2][0]) && MathUtil::is_zero_approx(rows[2][1]);
    }

    void orthonormalize() {
        Vec3 x_ = get_column(0);
        Vec3 y_ = get_column(1);
        Vec3 z_ = get_column(2);
        x_.normalize();
        y_ = y_ - x_ * x_.dot(y_);
        y_.normalize();
        z_ = z_ - x_ * x_.dot(z_) - y_ * y_.dot(z_);
        z_.normalize();
        set_column(0, x_);
        set_column(1, y_);
        set_column(2, z_);
    }

    Mat3 orthonormalized() const {
        Mat3 m = *this;
        m.orthonormalize();
        return m;
    }

    // Construct rotation matrix from quaternion
    void set_quaternion(const Quat& q) {
        double d = q.length_squared();
        double s = 2.0 / d;
        double xs = q.x*s, ys = q.y*s, zs = q.z*s;
        double wx = q.w*xs, wy = q.w*ys, wz = q.w*zs;
        double xx = q.x*xs, xy = q.x*ys, xz = q.x*zs;
        double yy = q.y*ys, yz = q.y*zs, zz = q.z*zs;
        rows[0] = Vec3(1.0-(yy+zz), xy-wz,       xz+wy);
        rows[1] = Vec3(xy+wz,       1.0-(xx+zz),  yz-wx);
        rows[2] = Vec3(xz-wy,       yz+wx,        1.0-(xx+yy));
    }

    // Construct rotation matrix from axis-angle
    void set_axis_angle(const Vec3& axis, double angle) {
        Vec3 axis_sq(axis.x*axis.x, axis.y*axis.y, axis.z*axis.z);
        double cosine = std::cos(angle);
        rows[0][0] = axis_sq.x + cosine * (1.0 - axis_sq.x);
        rows[1][1] = axis_sq.y + cosine * (1.0 - axis_sq.y);
        rows[2][2] = axis_sq.z + cosine * (1.0 - axis_sq.z);
        double sine = std::sin(angle);
        double t = 1.0 - cosine;
        double xyzt = axis.x * axis.y * t;
        double zyxs = axis.z * sine;
        rows[0][1] = xyzt - zyxs;
        rows[1][0] = xyzt + zyxs;
        xyzt = axis.x * axis.z * t;
        zyxs = axis.y * sine;
        rows[0][2] = xyzt + zyxs;
        rows[2][0] = xyzt - zyxs;
        xyzt = axis.y * axis.z * t;
        zyxs = axis.x * sine;
        rows[1][2] = xyzt - zyxs;
        rows[2][1] = xyzt + zyxs;
    }

    static Mat3 from_euler(const Vec3& euler, EulerOrder order = EulerOrder::YXZ) {
        Mat3 m;
        m.set_euler(euler, order);
        return m;
    }

    // Implemented in rotation_math.cpp
    void set_euler(const Vec3& euler, EulerOrder order = EulerOrder::YXZ);
    Vec3 get_euler(EulerOrder order = EulerOrder::YXZ) const;
    Quat get_quaternion() const;
    void get_axis_angle(Vec3& axis, double& angle) const;
    bool is_orthogonal() const;
    bool is_orthonormal() const;
    bool is_conformal() const;
    bool is_rotation() const;
    Vec3 log_rotation() const;
    double geodesic_distance(const Mat3& other) const;
};
