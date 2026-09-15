/*
 *
 * Demonstration scene: four CSG objects (union, intersection, difference,
 * and a nested CSG tree) rendered side by side on a ground plane.
 */

#include "rtweekend.h"

#include "bvh.h"
#include "camera.h"
#include "csg.h"
#include "hittable.h"
#include "hittable_list.h"
#include "material.h"
#include "sphere.h"


int main() {
    srand(42);

    hittable_list world;

    auto ground = make_shared<lambertian>(color(0.5, 0.5, 0.5));
    auto red    = make_shared<lambertian>(color(0.8, 0.1, 0.1));
    auto green  = make_shared<lambertian>(color(0.1, 0.8, 0.1));
    auto blue   = make_shared<lambertian>(color(0.1, 0.1, 0.8));
    auto white  = make_shared<lambertian>(color(0.9, 0.9, 0.9));
    auto gold   = make_shared<metal>(color(0.8, 0.6, 0.2), 0.1);

    // Ground
    world.add(make_shared<sphere>(point3(0, -100.5, -1), 100, ground));

    // --- CSG Union (left) ---
    auto u1 = make_shared<sphere>(point3(-2.5, 0, -1), 0.5, red);
    auto u2 = make_shared<sphere>(point3(-2.0, 0, -1), 0.5, blue);
    world.add(make_shared<csg_node>(u1, u2, csg_op::union_op));

    // --- CSG Intersection (center-left) ---
    auto i1 = make_shared<sphere>(point3(-0.25, 0, -1), 0.5, green);
    auto i2 = make_shared<sphere>(point3( 0.25, 0, -1), 0.5, white);
    world.add(make_shared<csg_node>(i1, i2, csg_op::intersection));

    // --- CSG Difference (center-right) ---
    auto d1 = make_shared<sphere>(point3(2.0, 0, -1), 0.5, gold);
    auto d2 = make_shared<sphere>(point3(2.3, 0.1, -1), 0.35, red);
    world.add(make_shared<csg_node>(d1, d2, csg_op::difference));

    // --- Nested CSG: (intersection lens) carved by a sphere ---
    // Inner: intersection of two overlapping spheres forms a lens shape
    // Outer: subtract a small sphere to carve a notch in the lens
    auto n_a = make_shared<sphere>(point3(4.0, 0, -1), 0.5, white);
    auto n_b = make_shared<sphere>(point3(4.3, 0, -1), 0.5, green);
    auto n_lens = make_shared<csg_node>(n_a, n_b, csg_op::intersection);
    auto n_cut = make_shared<sphere>(point3(4.15, 0.2, -1), 0.25, red);
    world.add(make_shared<csg_node>(n_lens, n_cut, csg_op::difference));

    camera cam;

    cam.aspect_ratio      = 16.0 / 9.0;
    cam.image_width       = 200;
    cam.samples_per_pixel = 10;
    cam.max_depth         = 10;
    cam.background        = color(0.70, 0.80, 1.00);

    cam.vfov     = 60;
    cam.lookfrom = point3(0.5, 1.5, 3.5);
    cam.lookat   = point3(0.5, 0, -1);
    cam.vup      = vec3(0, 1, 0);

    cam.defocus_angle = 0;

    cam.render(world);

    return 0;
}
