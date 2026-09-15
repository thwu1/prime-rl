#!/usr/bin/env python3
"""
Extend rt.py with Cube, Cylinder, Group, CSG primitives
and parent-chain coordinate transforms.
"""

with open('/app/rt.py', 'r') as f:
    code = f.read()

# ---------------------------------------------------------------
# 1. Replace Shape.normal_at to support parent-chain traversal
# ---------------------------------------------------------------
old_normal_at = """    def normal_at(self, world_point):
        inv = self.get_inverse()
        local_point = inv * world_point
        local_normal = self.local_normal_at(local_point)
        world_normal = transpose(inv) * local_normal
        world_normal.w = 0
        return normalize(world_normal)"""

new_normal_at = """    def normal_at(self, world_point):
        local_point = world_to_object(self, world_point)
        local_normal = self.local_normal_at(local_point)
        return normal_to_world(self, local_normal)"""

code = code.replace(old_normal_at, new_normal_at)

# ---------------------------------------------------------------
# 2. Append new primitives and support functions
# ---------------------------------------------------------------
new_code = '''

# ============================================================
# Parent-chain coordinate transforms (for Groups and CSG)
# ============================================================

def world_to_object(shape, pt):
    """Transform a world-space point into a shape's local space,
    traversing up through any parent group/CSG chain."""
    if shape.parent is not None:
        pt = world_to_object(shape.parent, pt)
    return shape.get_inverse() * pt

def normal_to_world(shape, normal):
    """Transform a local-space normal back to world space,
    traversing up through any parent group/CSG chain."""
    normal = transpose(shape.get_inverse()) * normal
    normal.w = 0
    normal = normalize(normal)
    if shape.parent is not None:
        normal = normal_to_world(shape.parent, normal)
    return normal


# ============================================================
# Cube (axis-aligned unit cube [-1,1]^3)
# ============================================================

class Cube(Shape):
    def local_intersect(self, ray):
        def check_axis(origin, direction):
            tmin_num = (-1 - origin)
            tmax_num = (1 - origin)
            if abs(direction) >= EPSILON:
                tmin = tmin_num / direction
                tmax = tmax_num / direction
            else:
                tmin = tmin_num * 1e12
                tmax = tmax_num * 1e12
            if tmin > tmax:
                tmin, tmax = tmax, tmin
            return tmin, tmax

        xtmin, xtmax = check_axis(ray.origin.x, ray.direction.x)
        ytmin, ytmax = check_axis(ray.origin.y, ray.direction.y)
        ztmin, ztmax = check_axis(ray.origin.z, ray.direction.z)

        tmin = max(xtmin, ytmin, ztmin)
        tmax = min(xtmax, ytmax, ztmax)

        if tmin > tmax:
            return []
        return [Intersection(tmin, self), Intersection(tmax, self)]

    def local_normal_at(self, p):
        maxc = max(abs(p.x), abs(p.y), abs(p.z))
        if maxc == abs(p.x):
            return vector(p.x, 0, 0)
        elif maxc == abs(p.y):
            return vector(0, p.y, 0)
        else:
            return vector(0, 0, p.z)


# ============================================================
# Cylinder (radius 1, y-axis, truncatable with caps)
# ============================================================

class Cylinder(Shape):
    def __init__(self):
        super().__init__()
        self.minimum = float('-inf')
        self.maximum = float('inf')
        self.closed = False

    def _check_cap(self, ray, t):
        x = ray.origin.x + t * ray.direction.x
        z = ray.origin.z + t * ray.direction.z
        return (x * x + z * z) <= 1.0 + EPSILON

    def _intersect_caps(self, ray):
        xs = []
        if not self.closed or abs(ray.direction.y) < EPSILON:
            return xs
        t = (self.minimum - ray.origin.y) / ray.direction.y
        if self._check_cap(ray, t):
            xs.append(Intersection(t, self))
        t = (self.maximum - ray.origin.y) / ray.direction.y
        if self._check_cap(ray, t):
            xs.append(Intersection(t, self))
        return xs

    def local_intersect(self, ray):
        a = ray.direction.x ** 2 + ray.direction.z ** 2
        xs = []
        if abs(a) >= EPSILON:
            b = 2 * (ray.origin.x * ray.direction.x +
                      ray.origin.z * ray.direction.z)
            c = ray.origin.x ** 2 + ray.origin.z ** 2 - 1
            disc = b * b - 4 * a * c
            if disc < 0:
                return []
            sd = math.sqrt(disc)
            t0 = (-b - sd) / (2 * a)
            t1 = (-b + sd) / (2 * a)
            if t0 > t1:
                t0, t1 = t1, t0
            y0 = ray.origin.y + t0 * ray.direction.y
            if self.minimum < y0 < self.maximum:
                xs.append(Intersection(t0, self))
            y1 = ray.origin.y + t1 * ray.direction.y
            if self.minimum < y1 < self.maximum:
                xs.append(Intersection(t1, self))
        xs.extend(self._intersect_caps(ray))
        return xs

    def local_normal_at(self, p):
        dist = p.x ** 2 + p.z ** 2
        if dist < 1 and p.y >= self.maximum - EPSILON:
            return vector(0, 1, 0)
        if dist < 1 and p.y <= self.minimum + EPSILON:
            return vector(0, -1, 0)
        return vector(p.x, 0, p.z)


# ============================================================
# Group (hierarchical shape container)
# ============================================================

class Group(Shape):
    def __init__(self):
        super().__init__()
        self.children = []

    def add_child(self, shape):
        shape.parent = self
        self.children.append(shape)

    def local_intersect(self, ray):
        xs = []
        for child in self.children:
            xs.extend(child.intersect(ray))
        return sorted(xs, key=lambda i: i.t)

    def local_normal_at(self, p):
        raise NotImplementedError("Groups do not have surface normals")


# ============================================================
# CSG (Constructive Solid Geometry)
# ============================================================

def intersection_allowed(op, lhit, inl, inr):
    """Determine if an intersection should be kept for the given CSG op."""
    if op == "union":
        return (lhit and not inr) or (not lhit and not inl)
    elif op == "intersection":
        return (lhit and inr) or (not lhit and inl)
    elif op == "difference":
        return (lhit and not inr) or (not lhit and inl)
    return False


class CSG(Shape):
    def __init__(self, operation, left, right):
        super().__init__()
        self.operation = operation
        self.left = left
        self.right = right
        left.parent = self
        right.parent = self

    def _includes(self, shape, target):
        """Check if target is the same as, or a descendant of, shape."""
        if isinstance(shape, Group):
            return any(self._includes(c, target) for c in shape.children)
        elif isinstance(shape, CSG):
            return (self._includes(shape.left, target) or
                    self._includes(shape.right, target))
        else:
            return shape is target

    def filter_intersections(self, xs):
        """Filter a sorted intersection list using this CSG's operation."""
        inl = False
        inr = False
        result = []
        for i in xs:
            lhit = self._includes(self.left, i.object)
            if intersection_allowed(self.operation, lhit, inl, inr):
                result.append(i)
            if lhit:
                inl = not inl
            else:
                inr = not inr
        return result

    def local_intersect(self, ray):
        left_xs = self.left.intersect(ray)
        right_xs = self.right.intersect(ray)
        xs = sorted(left_xs + right_xs, key=lambda i: i.t)
        return self.filter_intersections(xs)

    def local_normal_at(self, p):
        raise NotImplementedError("CSG shapes delegate normals to children")
'''

code += new_code

with open('/app/rt.py', 'w') as f:
    f.write(code)

print("rt.py extended with Cube, Cylinder, Group, CSG and parent-chain transforms.")
