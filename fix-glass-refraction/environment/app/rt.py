"""
Whitted-style ray tracer with reflection and refraction support.
Implements sphere and plane primitives with Phong lighting model.
"""
import math

EPSILON = 1e-5

# ============================================================
# Tuple (Point, Vector, Color)
# ============================================================

class Tuple:
    __slots__ = ('x', 'y', 'z', 'w')

    def __init__(self, x, y, z, w):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.w = float(w)

    def __add__(self, o):
        return Tuple(self.x + o.x, self.y + o.y, self.z + o.z, self.w + o.w)

    def __sub__(self, o):
        return Tuple(self.x - o.x, self.y - o.y, self.z - o.z, self.w - o.w)

    def __neg__(self):
        return Tuple(-self.x, -self.y, -self.z, -self.w)

    def __mul__(self, s):
        if isinstance(s, Tuple):
            return Tuple(self.x * s.x, self.y * s.y, self.z * s.z, 0)
        return Tuple(self.x * s, self.y * s, self.z * s, self.w * s)

    def __rmul__(self, s):
        return self * s

    def __truediv__(self, s):
        return Tuple(self.x / s, self.y / s, self.z / s, self.w / s)

    def __eq__(self, o):
        if not isinstance(o, Tuple):
            return NotImplemented
        return (abs(self.x - o.x) < EPSILON and abs(self.y - o.y) < EPSILON
                and abs(self.z - o.z) < EPSILON and abs(self.w - o.w) < EPSILON)

    def __repr__(self):
        return f"Tuple({self.x:.5f}, {self.y:.5f}, {self.z:.5f}, {self.w:.5f})"


def point(x, y, z):
    return Tuple(x, y, z, 1.0)

def vector(x, y, z):
    return Tuple(x, y, z, 0.0)

def color(r, g, b):
    return Tuple(r, g, b, 0.0)

def dot(a, b):
    return a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w

def cross(a, b):
    return vector(a.y * b.z - a.z * b.y,
                  a.z * b.x - a.x * b.z,
                  a.x * b.y - a.y * b.x)

def magnitude(v):
    return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z + v.w * v.w)

def normalize(v):
    m = magnitude(v)
    return Tuple(v.x / m, v.y / m, v.z / m, v.w / m)

def reflect(v, normal):
    return v - normal * 2 * dot(v, normal)


# ============================================================
# Matrix (4x4)
# ============================================================

class Matrix:
    def __init__(self, size=4, data=None):
        self.size = size
        if data is not None:
            self.data = [float(x) for x in data]
        else:
            self.data = [0.0] * (size * size)

    def __getitem__(self, key):
        r, c = key
        return self.data[r * self.size + c]

    def __setitem__(self, key, val):
        r, c = key
        self.data[r * self.size + c] = float(val)

    def __eq__(self, other):
        if not isinstance(other, Matrix):
            return NotImplemented
        if self.size != other.size:
            return False
        return all(abs(a - b) < EPSILON for a, b in zip(self.data, other.data))

    def __mul__(self, other):
        if isinstance(other, Tuple):
            x = self[0,0]*other.x + self[0,1]*other.y + self[0,2]*other.z + self[0,3]*other.w
            y = self[1,0]*other.x + self[1,1]*other.y + self[1,2]*other.z + self[1,3]*other.w
            z = self[2,0]*other.x + self[2,1]*other.y + self[2,2]*other.z + self[2,3]*other.w
            w = self[3,0]*other.x + self[3,1]*other.y + self[3,2]*other.z + self[3,3]*other.w
            return Tuple(x, y, z, w)
        elif isinstance(other, Matrix):
            m = Matrix(4)
            for r in range(4):
                for c in range(4):
                    m[r, c] = sum(self[r, k] * other[k, c] for k in range(4))
            return m
        return NotImplemented


def identity_matrix():
    return Matrix(4, [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])

def submatrix(m, del_row, del_col):
    s = m.size - 1
    result = Matrix(s)
    ri = 0
    for r in range(m.size):
        if r == del_row:
            continue
        ci = 0
        for c in range(m.size):
            if c == del_col:
                continue
            result[ri, ci] = m[r, c]
            ci += 1
        ri += 1
    return result

def minor(m, row, col):
    return determinant(submatrix(m, row, col))

def cofactor(m, row, col):
    mn = minor(m, row, col)
    return -mn if (row + col) % 2 == 1 else mn

def determinant(m):
    if m.size == 2:
        return m[0,0] * m[1,1] - m[0,1] * m[1,0]
    return sum(m[0, c] * cofactor(m, 0, c) for c in range(m.size))

def inverse(m):
    det = determinant(m)
    if abs(det) < EPSILON:
        raise ValueError("Matrix is not invertible")
    inv = Matrix(m.size)
    for r in range(m.size):
        for c in range(m.size):
            inv[c, r] = cofactor(m, r, c) / det
    return inv

def transpose(m):
    t = Matrix(m.size)
    for r in range(m.size):
        for c in range(m.size):
            t[r, c] = m[c, r]
    return t


# ============================================================
# Transformations
# ============================================================

def translation(x, y, z):
    m = identity_matrix()
    m[0,3] = x; m[1,3] = y; m[2,3] = z
    return m

def scaling(x, y, z):
    m = identity_matrix()
    m[0,0] = x; m[1,1] = y; m[2,2] = z
    return m

def rotation_x(r):
    m = identity_matrix()
    c, s = math.cos(r), math.sin(r)
    m[1,1] = c; m[1,2] = -s; m[2,1] = s; m[2,2] = c
    return m

def rotation_y(r):
    m = identity_matrix()
    c, s = math.cos(r), math.sin(r)
    m[0,0] = c; m[0,2] = s; m[2,0] = -s; m[2,2] = c
    return m

def rotation_z(r):
    m = identity_matrix()
    c, s = math.cos(r), math.sin(r)
    m[0,0] = c; m[0,1] = -s; m[1,0] = s; m[1,1] = c
    return m

def view_transform(from_pt, to_pt, up):
    forward = normalize(to_pt - from_pt)
    left = cross(forward, normalize(up))
    true_up = cross(left, forward)
    orientation = Matrix(4, [
        left.x,     left.y,     left.z,    0,
        true_up.x,  true_up.y,  true_up.z, 0,
        -forward.x, -forward.y, -forward.z, 0,
        0,          0,          0,          1,
    ])
    return orientation * translation(-from_pt.x, -from_pt.y, -from_pt.z)


# ============================================================
# Ray
# ============================================================

class Ray:
    def __init__(self, origin, direction):
        self.origin = origin
        self.direction = direction

def ray_position(ray, t):
    return ray.origin + ray.direction * t

def transform_ray(ray, matrix):
    return Ray(matrix * ray.origin, matrix * ray.direction)


# ============================================================
# Material
# ============================================================

class Material:
    def __init__(self):
        self.color = color(1, 1, 1)
        self.ambient = 0.1
        self.diffuse = 0.9
        self.specular = 0.9
        self.shininess = 200.0
        self.reflective = 0.0
        self.transparency = 0.0
        self.refractive_index = 1.0
        self.pattern = None


# ============================================================
# Shapes
# ============================================================

class Shape:
    _id_counter = 0

    def __init__(self):
        Shape._id_counter += 1
        self._id = Shape._id_counter
        self.transform = identity_matrix()
        self.material = Material()
        self.parent = None
        self._inverse = None

    def get_inverse(self):
        if self._inverse is None:
            self._inverse = inverse(self.transform)
        return self._inverse

    def intersect(self, world_ray):
        local_ray = transform_ray(world_ray, self.get_inverse())
        return self.local_intersect(local_ray)

    def normal_at(self, world_point):
        inv = self.get_inverse()
        local_point = inv * world_point
        local_normal = self.local_normal_at(local_point)
        world_normal = transpose(inv) * local_normal
        world_normal.w = 0
        return normalize(world_normal)


class Sphere(Shape):
    def local_intersect(self, ray):
        sphere_to_ray = ray.origin - point(0, 0, 0)
        a = dot(ray.direction, ray.direction)
        b = 2 * dot(ray.direction, sphere_to_ray)
        c = dot(sphere_to_ray, sphere_to_ray) - 1
        disc = b * b - 4 * a * c
        if disc < 0:
            return []
        sd = math.sqrt(disc)
        t1 = (-b - sd) / (2 * a)
        t2 = (-b + sd) / (2 * a)
        return [Intersection(t1, self), Intersection(t2, self)]

    def local_normal_at(self, p):
        return p - point(0, 0, 0)


class Plane(Shape):
    def local_intersect(self, ray):
        if abs(ray.direction.y) < EPSILON:
            return []
        t = -ray.origin.y / ray.direction.y
        return [Intersection(t, self)]

    def local_normal_at(self, p):
        return vector(0, 1, 0)


def glass_sphere():
    s = Sphere()
    s.material.transparency = 1.0
    s.material.refractive_index = 1.5
    return s


# ============================================================
# Intersection
# ============================================================

class Intersection:
    def __init__(self, t, obj):
        self.t = float(t)
        self.object = obj

def intersections(*args):
    return sorted(list(args), key=lambda i: i.t)

def hit(xs):
    for i in sorted(xs, key=lambda i: i.t):
        if i.t >= 0:
            return i
    return None


# ============================================================
# Computations (prepare_computations)
# ============================================================

class Computations:
    pass

def prepare_computations(i, ray, xs=None):
    comps = Computations()
    comps.t = i.t
    comps.object = i.object
    comps.point = ray_position(ray, comps.t)
    comps.eyev = -ray.direction
    comps.normalv = comps.object.normal_at(comps.point)

    if dot(comps.normalv, comps.eyev) < 0:
        comps.inside = True
        comps.normalv = -comps.normalv
    else:
        comps.inside = False

    comps.reflectv = reflect(ray.direction, comps.normalv)
    comps.over_point = comps.point + comps.normalv * EPSILON
    comps.under_point = comps.point - comps.normalv * EPSILON

    # Compute n1 and n2 for refraction via the containers algorithm
    if xs is None:
        xs = [i]

    containers = []
    comps.n1 = 1.0
    comps.n2 = 1.0

    for ix in xs:
        if ix is i:
            if len(containers) == 0:
                comps.n1 = 1.0
            else:
                comps.n1 = containers[-1].material.refractive_index

        obj = ix.object
        if obj in containers:
            containers.remove(obj)
        else:
            containers.append(obj)

        if ix is i:
            if len(containers) == 0:
                comps.n2 = 1.0
            else:
                comps.n2 = containers[-1].material.refractive_index
            break

    return comps


# ============================================================
# Lighting
# ============================================================

class PointLight:
    def __init__(self, position, intensity):
        self.position = position
        self.intensity = intensity


def lighting(material, shape, light, pt, eyev, normalv, in_shadow=False):
    if material.pattern is not None:
        c = pattern_at_shape(material.pattern, shape, pt)
    else:
        c = material.color

    effective_color = c * light.intensity
    lightv = normalize(light.position - pt)
    ambient = effective_color * material.ambient

    if in_shadow:
        return ambient

    light_dot_normal = dot(lightv, normalv)
    if light_dot_normal < 0:
        diffuse = color(0, 0, 0)
        specular = color(0, 0, 0)
    else:
        diffuse = effective_color * material.diffuse * light_dot_normal
        reflectv = reflect(-lightv, normalv)
        reflect_dot_eye = dot(reflectv, eyev)
        if reflect_dot_eye <= 0:
            specular = color(0, 0, 0)
        else:
            factor = math.pow(reflect_dot_eye, material.shininess)
            specular = light.intensity * material.specular * factor

    return ambient + diffuse + specular


# ============================================================
# Patterns (minimal support for testing)
# ============================================================

class TestPattern:
    def __init__(self):
        self.transform = identity_matrix()
        self._inverse = None

    def get_inverse(self):
        if self._inverse is None:
            self._inverse = inverse(self.transform)
        return self._inverse

def test_pattern():
    return TestPattern()

def pattern_at_shape(pattern, shape, world_point):
    object_point = shape.get_inverse() * world_point
    pattern_point = pattern.get_inverse() * object_point
    return color(pattern_point.x, pattern_point.y, pattern_point.z)


# ============================================================
# World
# ============================================================

class World:
    def __init__(self):
        self.objects = []
        self.light = None


def default_world():
    w = World()
    w.light = PointLight(point(-10, 10, -10), color(1, 1, 1))
    s1 = Sphere()
    s1.material.color = color(0.8, 1.0, 0.6)
    s1.material.diffuse = 0.7
    s1.material.specular = 0.2
    s2 = Sphere()
    s2.transform = scaling(0.5, 0.5, 0.5)
    s2._inverse = None
    w.objects = [s1, s2]
    return w


def intersect_world(world, ray):
    all_xs = []
    for obj in world.objects:
        all_xs.extend(obj.intersect(ray))
    return sorted(all_xs, key=lambda i: i.t)


def is_shadowed(world, pt):
    v = world.light.position - pt
    distance = magnitude(v)
    direction = normalize(v)
    r = Ray(pt, direction)
    xs = intersect_world(world, r)
    h = hit(xs)
    return h is not None and h.t < distance


def reflected_color(world, comps, remaining=5):
    if remaining <= 0:
        return color(0, 0, 0)
    if comps.object.material.reflective == 0:
        return color(0, 0, 0)
    reflect_ray = Ray(comps.over_point, comps.reflectv)
    c = color_at(world, reflect_ray, remaining - 1)
    return c * comps.object.material.reflective


def refracted_color(world, comps, remaining=5):
    if remaining <= 0:
        return color(0, 0, 0)
    if comps.object.material.transparency == 0:
        return color(0, 0, 0)

    n_ratio = comps.n1 / comps.n2
    cos_i = dot(comps.eyev, comps.normalv)
    sin2_t = n_ratio**2 * (1 - cos_i**2)

    if sin2_t > 1.0:
        return color(0, 0, 0)

    cos_t = math.sqrt(1.0 - sin2_t)

    direction = comps.normalv * (n_ratio * cos_i - cos_t) - comps.eyev * n_ratio
    refract_ray = Ray(comps.under_point, direction)

    return color_at(world, refract_ray, remaining - 1) * comps.object.material.transparency


def schlick(comps):
    cos = dot(comps.eyev, comps.normalv)

    if comps.n1 > comps.n2:
        n = comps.n1 / comps.n2
        sin2_t = n**2 * (1.0 - cos**2)
        if sin2_t > 1.0:
            return 1.0
        cos_t = math.sqrt(1.0 - sin2_t)
        cos = cos_t

    r0 = ((comps.n1 - comps.n2) / (comps.n1 + comps.n2))**2
    return r0 + (1 - r0) * (1 - cos)**5


def shade_hit(world, comps, remaining=5):
    shadowed = is_shadowed(world, comps.over_point)
    surface = lighting(comps.object.material, comps.object, world.light,
                       comps.over_point, comps.eyev, comps.normalv, shadowed)
    reflected = reflected_color(world, comps, remaining)
    refracted = refracted_color(world, comps, remaining)

    material = comps.object.material
    if material.reflective > 0 and material.transparency > 0:
        reflectance = schlick(comps)
        return surface + reflected * reflectance + refracted * (1 - reflectance)
    return surface + reflected + refracted


def color_at(world, ray, remaining=5):
    xs = intersect_world(world, ray)
    h = hit(xs)
    if h is None:
        return color(0, 0, 0)
    comps = prepare_computations(h, ray, xs)
    return shade_hit(world, comps, remaining)


# ============================================================
# Camera
# ============================================================

class Camera:
    def __init__(self, hsize, vsize, field_of_view):
        self.hsize = hsize
        self.vsize = vsize
        self.field_of_view = field_of_view
        self.transform = identity_matrix()

        half_view = math.tan(field_of_view / 2)
        aspect = hsize / vsize
        if aspect >= 1:
            self.half_width = half_view
            self.half_height = half_view / aspect
        else:
            self.half_width = half_view * aspect
            self.half_height = half_view

        self.pixel_size = (self.half_width * 2) / hsize


def ray_for_pixel(camera, px, py):
    xoffset = (px + 0.5) * camera.pixel_size
    yoffset = (py + 0.5) * camera.pixel_size
    world_x = camera.half_width - xoffset
    world_y = camera.half_height - yoffset
    inv = inverse(camera.transform)
    pixel = inv * point(world_x, world_y, -1)
    origin = inv * point(0, 0, 0)
    direction = normalize(pixel - origin)
    return Ray(origin, direction)


def render(camera, world):
    image = Canvas(camera.hsize, camera.vsize)
    for y in range(camera.vsize):
        for x in range(camera.hsize):
            ray = ray_for_pixel(camera, x, y)
            c = color_at(world, ray)
            image.write_pixel(x, y, c)
    return image


# ============================================================
# Canvas
# ============================================================

class Canvas:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pixels = [[color(0, 0, 0) for _ in range(width)] for _ in range(height)]

    def write_pixel(self, x, y, c):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y][x] = c

    def pixel_at(self, x, y):
        return self.pixels[y][x]

    def to_ppm(self):
        lines = ["P3", f"{self.width} {self.height}", "255"]
        for y in range(self.height):
            row = []
            for x in range(self.width):
                p = self.pixels[y][x]
                r = max(0, min(255, int(round(p.x * 255))))
                g = max(0, min(255, int(round(p.y * 255))))
                b = max(0, min(255, int(round(p.z * 255))))
                row.extend([str(r), str(g), str(b)])
            line = " ".join(row)
            while len(line) > 70:
                idx = line[:70].rfind(' ')
                if idx == -1:
                    break
                lines.append(line[:idx])
                line = line[idx + 1:]
            lines.append(line)
        lines.append("")
        return "\n".join(lines)
