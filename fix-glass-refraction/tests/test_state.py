
import sys
import math
import os
import subprocess
import pytest
sys.path.insert(0, '/app')
from rt import *


# ================================================================
# Cube Tests (from Ray Tracer Challenge specification)
# ================================================================

class TestCubeIntersect:
    """Ray-cube intersection: 7 hit scenarios + 6 miss scenarios."""

    @pytest.mark.parametrize("origin,direction,t1,t2", [
        (point(5, 0.5, 0),  vector(-1, 0, 0),  4, 6),
        (point(-5, 0.5, 0), vector(1, 0, 0),   4, 6),
        (point(0.5, 5, 0),  vector(0, -1, 0),  4, 6),
        (point(0.5, -5, 0), vector(0, 1, 0),   4, 6),
        (point(0.5, 0, 5),  vector(0, 0, -1),  4, 6),
        (point(0.5, 0, -5), vector(0, 0, 1),   4, 6),
        (point(0, 0.5, 0),  vector(0, 0, 1),  -1, 1),
    ])
    def test_ray_hits_cube(self, origin, direction, t1, t2):
        c = Cube()
        r = Ray(origin, direction)
        xs = c.local_intersect(r)
        assert len(xs) == 2
        assert abs(xs[0].t - t1) < EPSILON
        assert abs(xs[1].t - t2) < EPSILON

    @pytest.mark.parametrize("origin,direction", [
        (point(-2, 0, 0),  vector(0.2673, 0.5345, 0.8018)),
        (point(0, -2, 0),  vector(0.8018, 0.2673, 0.5345)),
        (point(0, 0, -2),  vector(0.5345, 0.8018, 0.2673)),
        (point(2, 0, 2),   vector(0, 0, -1)),
        (point(0, 2, 2),   vector(0, -1, 0)),
        (point(2, 2, 0),   vector(-1, 0, 0)),
    ])
    def test_ray_misses_cube(self, origin, direction):
        c = Cube()
        r = Ray(origin, direction)
        xs = c.local_intersect(r)
        assert len(xs) == 0


class TestCubeNormal:
    """Normal vectors on cube surfaces (8 cases including corners)."""

    @pytest.mark.parametrize("pt,expected", [
        (point(1, 0.5, -0.8),   vector(1, 0, 0)),
        (point(-1, -0.2, 0.9),  vector(-1, 0, 0)),
        (point(-0.4, 1, -0.1),  vector(0, 1, 0)),
        (point(0.3, -1, -0.7),  vector(0, -1, 0)),
        (point(-0.6, 0.3, 1),   vector(0, 0, 1)),
        (point(0.4, 0.4, -1),   vector(0, 0, -1)),
        (point(1, 1, 1),        vector(1, 0, 0)),
        (point(-1, -1, -1),     vector(-1, 0, 0)),
    ])
    def test_cube_normal(self, pt, expected):
        c = Cube()
        n = c.local_normal_at(pt)
        assert n == expected


# ================================================================
# Cylinder Tests
# ================================================================

class TestCylinderIntersect:
    """Ray-cylinder intersections: miss and strike scenarios."""

    @pytest.mark.parametrize("origin,direction", [
        (point(1, 0, 0),  vector(0, 1, 0)),
        (point(0, 0, 0),  vector(0, 1, 0)),
        (point(0, 0, -5), vector(1, 1, 1)),
    ])
    def test_ray_misses_cylinder(self, origin, direction):
        cyl = Cylinder()
        d = normalize(direction)
        r = Ray(origin, d)
        xs = cyl.local_intersect(r)
        assert len(xs) == 0

    @pytest.mark.parametrize("origin,direction,t0,t1", [
        (point(1, 0, -5),   vector(0, 0, 1),   5.0, 5.0),
        (point(0, 0, -5),   vector(0, 0, 1),   4.0, 6.0),
        (point(0.5, 0, -5), vector(0.1, 1, 1), 6.80798, 7.08872),
    ])
    def test_ray_strikes_cylinder(self, origin, direction, t0, t1):
        cyl = Cylinder()
        d = normalize(direction)
        r = Ray(origin, d)
        xs = cyl.local_intersect(r)
        assert len(xs) == 2
        assert abs(xs[0].t - t0) < 1e-4, f"xs[0].t={xs[0].t}, expected {t0}"
        assert abs(xs[1].t - t1) < 1e-4, f"xs[1].t={xs[1].t}, expected {t1}"


class TestCylinderConstrained:
    """Truncated cylinder with min=1, max=2."""

    @pytest.mark.parametrize("origin,direction,count", [
        (point(0, 1.5, 0),  vector(0.1, 1, 0), 0),
        (point(0, 3, -5),   vector(0, 0, 1),   0),
        (point(0, 0, -5),   vector(0, 0, 1),   0),
        (point(0, 2, -5),   vector(0, 0, 1),   0),
        (point(0, 1, -5),   vector(0, 0, 1),   0),
        (point(0, 1.5, -2), vector(0, 0, 1),   2),
    ])
    def test_constrained_cylinder(self, origin, direction, count):
        cyl = Cylinder()
        cyl.minimum = 1
        cyl.maximum = 2
        d = normalize(direction)
        r = Ray(origin, d)
        xs = cyl.local_intersect(r)
        assert len(xs) == count


class TestCylinderCaps:
    """Closed cylinder with end caps."""

    @pytest.mark.parametrize("origin,direction,count", [
        (point(0, 3, 0),   vector(0, -1, 0), 2),
        (point(0, 3, -2),  vector(0, -1, 2), 2),
        (point(0, 4, -2),  vector(0, -1, 1), 2),
        (point(0, 0, -2),  vector(0, 1, 2),  2),
        (point(0, -1, -2), vector(0, 1, 1),  2),
    ])
    def test_closed_cylinder_caps(self, origin, direction, count):
        cyl = Cylinder()
        cyl.minimum = 1
        cyl.maximum = 2
        cyl.closed = True
        d = normalize(direction)
        r = Ray(origin, d)
        xs = cyl.local_intersect(r)
        assert len(xs) == count, f"Expected {count} hits, got {len(xs)}"


class TestCylinderNormal:
    """Normal vectors on cylinder wall and caps."""

    @pytest.mark.parametrize("pt,expected", [
        (point(1, 0, 0),  vector(1, 0, 0)),
        (point(0, 5, -1), vector(0, 0, -1)),
        (point(0, -2, 1), vector(0, 0, 1)),
        (point(-1, 1, 0), vector(-1, 0, 0)),
    ])
    def test_cylinder_wall_normal(self, pt, expected):
        cyl = Cylinder()
        n = cyl.local_normal_at(pt)
        assert n == expected

    @pytest.mark.parametrize("pt,expected", [
        (point(0, 1, 0),   vector(0, -1, 0)),
        (point(0.5, 1, 0), vector(0, -1, 0)),
        (point(0, 1, 0.5), vector(0, -1, 0)),
        (point(0, 2, 0),   vector(0, 1, 0)),
        (point(0.5, 2, 0), vector(0, 1, 0)),
        (point(0, 2, 0.5), vector(0, 1, 0)),
    ])
    def test_cylinder_cap_normal(self, pt, expected):
        cyl = Cylinder()
        cyl.minimum = 1
        cyl.maximum = 2
        cyl.closed = True
        n = cyl.local_normal_at(pt)
        assert n == expected


# ================================================================
# CSG Tests
# ================================================================

class TestCSGIntersectionAllowed:
    """24-entry truth table for CSG intersection_allowed."""

    @pytest.mark.parametrize("op,lhit,inl,inr,expected", [
        ("union", True, True, True, False),
        ("union", True, True, False, True),
        ("union", True, False, True, False),
        ("union", True, False, False, True),
        ("union", False, True, True, False),
        ("union", False, True, False, False),
        ("union", False, False, True, True),
        ("union", False, False, False, True),
        ("intersection", True, True, True, True),
        ("intersection", True, True, False, False),
        ("intersection", True, False, True, True),
        ("intersection", True, False, False, False),
        ("intersection", False, True, True, True),
        ("intersection", False, True, False, True),
        ("intersection", False, False, True, False),
        ("intersection", False, False, False, False),
        ("difference", True, True, True, False),
        ("difference", True, True, False, True),
        ("difference", True, False, True, False),
        ("difference", True, False, False, True),
        ("difference", False, True, True, True),
        ("difference", False, True, False, True),
        ("difference", False, False, True, False),
        ("difference", False, False, False, False),
    ])
    def test_intersection_allowed(self, op, lhit, inl, inr, expected):
        result = intersection_allowed(op, lhit, inl, inr)
        assert result == expected, (
            f"intersection_allowed({op!r}, {lhit}, {inl}, {inr}) "
            f"= {result}, expected {expected}"
        )


class TestCSGFilter:
    """CSG filter_intersections produces correct subset for each operation."""

    @pytest.mark.parametrize("operation,x0,x1", [
        ("union", 0, 3),
        ("intersection", 1, 2),
        ("difference", 0, 1),
    ])
    def test_filter_intersections(self, operation, x0, x1):
        s1 = Sphere()
        s2 = Cube()
        c = CSG(operation, s1, s2)
        xs = [
            Intersection(1, s1),
            Intersection(2, s2),
            Intersection(3, s1),
            Intersection(4, s2),
        ]
        result = c.filter_intersections(xs)
        assert len(result) == 2
        assert result[0] is xs[x0]
        assert result[1] is xs[x1]


class TestCSGRayHit:
    """Ray hits a CSG union of two overlapping spheres."""

    def test_ray_hits_csg_union(self):
        s1 = Sphere()
        s2 = Sphere()
        s2.transform = translation(0, 0, 0.5)
        s2._inverse = None
        c = CSG("union", s1, s2)
        r = Ray(point(0, 0, -5), vector(0, 0, 1))
        xs = c.local_intersect(r)
        assert len(xs) == 2
        assert abs(xs[0].t - 4) < EPSILON
        assert xs[0].object is s1
        assert abs(xs[1].t - 6.5) < EPSILON
        assert xs[1].object is s2


class TestCSGDifference:
    """CSG difference: sphere minus a cylinder produces hole."""

    def test_csg_difference_intersect(self):
        sphere = Sphere()
        cyl = Cylinder()
        cyl.minimum = -2
        cyl.maximum = 2
        cyl.closed = True
        cyl.transform = scaling(0.3, 1, 0.3)
        cyl._inverse = None
        c = CSG("difference", sphere, cyl)
        # Ray along z-axis through center
        r = Ray(point(0, 0, -5), vector(0, 0, 1))
        xs = c.local_intersect(r)
        assert len(xs) == 4, f"Expected 4 intersections, got {len(xs)}"
        assert xs[0].object is sphere
        assert xs[-1].object is sphere


# ================================================================
# Group Tests
# ================================================================

class TestGroupIntersect:
    """Group intersection from book scenarios."""

    def test_empty_group(self):
        g = Group()
        r = Ray(point(0, 0, 0), vector(0, 0, 1))
        xs = g.local_intersect(r)
        assert len(xs) == 0

    def test_nonempty_group(self):
        g = Group()
        s1 = Sphere()
        s2 = Sphere()
        s2.transform = translation(0, 0, -3)
        s2._inverse = None
        s3 = Sphere()
        s3.transform = translation(5, 0, 0)
        s3._inverse = None
        g.add_child(s1)
        g.add_child(s2)
        g.add_child(s3)
        r = Ray(point(0, 0, -5), vector(0, 0, 1))
        xs = g.local_intersect(r)
        assert len(xs) == 4
        assert xs[0].object is s2
        assert xs[1].object is s2
        assert xs[2].object is s1
        assert xs[3].object is s1

    def test_transformed_group(self):
        g = Group()
        g.transform = scaling(2, 2, 2)
        g._inverse = None
        s = Sphere()
        s.transform = translation(5, 0, 0)
        s._inverse = None
        g.add_child(s)
        r = Ray(point(10, 0, -10), vector(0, 0, 1))
        xs = g.intersect(r)
        assert len(xs) == 2


class TestGroupNormal:
    """Normal computation must traverse group parent chain."""

    def test_normal_on_child_in_group(self):
        g = Group()
        g.transform = scaling(2, 2, 2)
        g._inverse = None
        s = Sphere()
        s.transform = translation(5, 0, 0)
        s._inverse = None
        g.add_child(s)
        n = s.normal_at(point(10, 0, -2))
        assert n.z < -0.5, f"Expected normal with negative z, got {n}"
        length = math.sqrt(n.x**2 + n.y**2 + n.z**2)
        assert abs(length - 1.0) < EPSILON


# ================================================================
# Integration Tests
# ================================================================

class TestBaseRender:
    """Sanity check: base render pipeline still works after modifications."""

    def test_render_default_world(self):
        w = default_world()
        cam = Camera(11, 11, math.pi / 2)
        cam.transform = view_transform(
            point(0, 0, -5), point(0, 0, 0), vector(0, 1, 0)
        )
        image = render(cam, w)
        p = image.pixel_at(5, 5)
        assert abs(p.x - 0.38066) < 0.01
        assert abs(p.y - 0.47583) < 0.01
        assert abs(p.z - 0.28550) < 0.01


class TestCubeRender:
    """Integration: render a scene with a red cube and verify center pixel."""

    def test_render_cube_scene(self):
        w = World()
        w.light = PointLight(point(-10, 10, -10), color(1, 1, 1))
        c = Cube()
        c.material.color = color(1, 0, 0)
        w.objects.append(c)

        cam = Camera(11, 11, math.pi / 2)
        cam.transform = view_transform(
            point(0, 0, -5), point(0, 0, 0), vector(0, 1, 0)
        )
        image = render(cam, w)
        p = image.pixel_at(5, 5)
        assert abs(p.x - 0.583) < 0.06, f"red: {p.x:.4f}, expected ~0.583"
        assert p.y < 0.05, f"green: {p.y:.4f}, expected near 0"
        assert p.z < 0.05, f"blue: {p.z:.4f}, expected near 0"


class TestPPMOutput:
    """Verify the final rendered scene PPM file."""

    def test_ppm_exists(self):
        assert os.path.exists('/app/output.ppm'), \
            "/app/output.ppm not found. Did you render the scene?"

    def test_ppm_valid_header(self):
        with open('/app/output.ppm', 'r') as f:
            lines = f.readlines()
        assert len(lines) >= 4, "PPM file too short"
        assert lines[0].strip() == 'P3', f"Expected P3 header, got {lines[0].strip()!r}"
        dims = lines[1].strip().split()
        assert len(dims) == 2, f"Expected 'width height', got {lines[1].strip()!r}"
        w, h = int(dims[0]), int(dims[1])
        assert w == 100, f"Expected width 100, got {w}"
        assert h == 75, f"Expected height 75, got {h}"
        assert lines[2].strip() == '255', f"Expected max 255, got {lines[2].strip()!r}"

    def test_ppm_has_rendered_content(self):
        with open('/app/output.ppm', 'r') as f:
            content = f.read()
        values = []
        for line in content.strip().split('\n')[3:]:
            for v in line.split():
                try:
                    values.append(int(v))
                except ValueError:
                    pass
        nonzero = sum(1 for v in values if v > 0)
        total = len(values)
        assert total > 0, "No pixel data found in PPM"
        assert nonzero > total * 0.05, (
            f"Only {nonzero}/{total} non-zero values — "
            f"scene appears mostly black, likely not rendering correctly"
        )

    def test_ppm_has_color_variety(self):
        """Verify multiple distinct objects rendered (different color regions)."""
        with open('/app/output.ppm', 'r') as f:
            content = f.read()
        vals = []
        for line in content.strip().split('\n')[3:]:
            vals.extend(int(v) for v in line.split() if v.strip())
        pixels = [(vals[i], vals[i+1], vals[i+2])
                   for i in range(0, len(vals) - 2, 3)]
        red_dominant = sum(1 for r, g, b in pixels if r > 50 and r > g and r > b)
        blue_dominant = sum(1 for r, g, b in pixels if b > 50 and b > r and b > g)
        gray_ish = sum(1 for r, g, b in pixels
                       if r > 50 and abs(r - g) < 30 and abs(r - b) < 30)
        assert red_dominant > 10, f"No red-dominant pixels found (cube missing?)"
        assert blue_dominant > 10, f"No blue-dominant pixels found (CSG sphere missing?)"
        assert gray_ish > 10, f"No gray pixels found (floor missing?)"


# ================================================================
# Makefile + netpbm Pipeline Test
# ================================================================

class TestMakePipeline:
    """The Makefile verify target must pass using netpbm tools."""

    def test_make_verify(self):
        """Validates output.ppm via pamfile and ppmhist (netpbm)."""
        result = subprocess.run(
            ['make', '-C', '/app', 'verify'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"make verify failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
