/*
 *
 * Standalone test for CSG boolean operations.
 * Compile: g++ -std=c++11 -O2 -I/app/src -o test_csg test_csg_intersections.cc
 */

#include "rtweekend.h"
#include "sphere.h"
#include "csg.h"
#include "material.h"

#include <iostream>
#include <cmath>

static bool approx(double a, double b, double eps = 0.02) {
    return std::fabs(a - b) < eps;
}

int main() {
    int passed = 0;
    int total  = 0;

    auto mat = make_shared<lambertian>(color(0.5, 0.5, 0.5));

    /*
     * Geometry:
     *   Sphere A: center (0, 0, 0),   radius 1.0
     *   Sphere B: center (0.6, 0, 0), radius 1.0
     *
     * Ray r1: origin (-5, 0, 0), direction (1, 0, 0)
     *   A intersections: t = 4.0 (enter), t = 6.0 (exit)
     *   B intersections: t = 4.6 (enter), t = 6.6 (exit)
     */

    auto sA = make_shared<sphere>(point3(0, 0, 0),   1.0, mat);
    auto sB = make_shared<sphere>(point3(0.6, 0, 0), 1.0, mat);

    ray r1(point3(-5, 0, 0), vec3(1, 0, 0));
    hit_record rec;

    /* ----- Test 1: CSG Intersection first hit ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::intersection);
        // Intersection region: [max(4.0,4.6), min(6.0,6.6)] = [4.6, 6.0]
        // First hit at t = 4.6
        if (csg->hit(r1, interval(0.001, 1e8), rec) && approx(rec.t, 4.6)) {
            passed++;
            std::cout << "PASS test1: intersection hit t=" << rec.t << "\n";
        } else {
            std::cout << "FAIL test1: intersection hit t="
                      << rec.t << " expected 4.6\n";
        }
    }

    /* ----- Test 2: CSG Difference first hit ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::difference);
        // Difference A-B region: [4.0, 4.6]
        // First hit at t = 4.0
        if (csg->hit(r1, interval(0.001, 1e8), rec) && approx(rec.t, 4.0)) {
            passed++;
            std::cout << "PASS test2: difference hit t=" << rec.t << "\n";
        } else {
            std::cout << "FAIL test2: difference hit t="
                      << rec.t << " expected 4.0\n";
        }
    }

    /* ----- Test 3: CSG Union first hit ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::union_op);
        // Union region: [4.0, 6.6]
        // First hit at t = 4.0
        if (csg->hit(r1, interval(0.001, 1e8), rec) && approx(rec.t, 4.0)) {
            passed++;
            std::cout << "PASS test3: union hit t=" << rec.t << "\n";
        } else {
            std::cout << "FAIL test3: union hit t="
                      << rec.t << " expected 4.0\n";
        }
    }

    /* ----- Test 4: Ray misses both spheres ----- */
    {
        total++;
        ray r_miss(point3(-5, 5, 0), vec3(1, 0, 0));
        auto csg = make_shared<csg_node>(sA, sB, csg_op::union_op);
        if (!csg->hit(r_miss, interval(0.001, 1e8), rec)) {
            passed++;
            std::cout << "PASS test4: miss correctly\n";
        } else {
            std::cout << "FAIL test4: should miss, hit at t=" << rec.t << "\n";
        }
    }

    /* ----- Test 5: Intersection normal direction ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::intersection);
        csg->hit(r1, interval(0.001, 1e8), rec);
        // At t=4.6, hit is on B's front surface.
        // Normal should point toward -x (facing the incoming ray).
        if (approx(rec.normal.x(), -1.0, 0.05) &&
            approx(rec.normal.y(), 0.0, 0.05) &&
            approx(rec.normal.z(), 0.0, 0.05) &&
            rec.front_face == true) {
            passed++;
            std::cout << "PASS test5: intersection normal correct\n";
        } else {
            std::cout << "FAIL test5: normal=(" << rec.normal.x() << ","
                      << rec.normal.y() << "," << rec.normal.z()
                      << ") front_face=" << rec.front_face << "\n";
        }
    }

    /* ----- Test 6: Difference exit point ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::difference);
        hit_record rec1, rec2;
        csg->hit(r1, interval(0.001, 1e8), rec1);
        // Entry at t=4.0. Exit should be at t=4.6 (where ray enters B).
        bool got_exit = csg->hit(r1, interval(rec1.t + 0.01, 1e8), rec2);
        if (got_exit && approx(rec2.t, 4.6)) {
            passed++;
            std::cout << "PASS test6: difference exit t=" << rec2.t << "\n";
        } else {
            if (got_exit)
                std::cout << "FAIL test6: difference exit t="
                          << rec2.t << " expected 4.6\n";
            else
                std::cout << "FAIL test6: no exit found after entry\n";
        }
    }

    /* ----- Test 7: Intersection miss when ray hits only A ----- */
    {
        total++;
        // Ray along y-axis at x=-0.5:
        //   Distance to A center (0,0,0): 0.5 < 1.0 -> hits A
        //   Distance to B center (0.6,0,0): 1.1 > 1.0 -> misses B
        ray r2(point3(-0.5, -5, 0), vec3(0, 1, 0));
        auto csg = make_shared<csg_node>(sA, sB, csg_op::intersection);
        if (!csg->hit(r2, interval(0.001, 1e8), rec)) {
            passed++;
            std::cout << "PASS test7: intersection misses when only A hit\n";
        } else {
            std::cout << "FAIL test7: intersection should miss, hit t=" << rec.t << "\n";
        }
    }

    /* ----- Test 8: Difference = A alone when ray misses B ----- */
    {
        total++;
        ray r2(point3(-0.5, -5, 0), vec3(0, 1, 0));
        auto csg = make_shared<csg_node>(sA, sB, csg_op::difference);
        // A: oc=(0.5,5,0), a=1, h=5, c=24.25, disc=0.75, sqrt=0.866
        // t_near = 5 - 0.866 = 4.134
        if (csg->hit(r2, interval(0.001, 1e8), rec) && approx(rec.t, 4.134)) {
            passed++;
            std::cout << "PASS test8: difference A-only t=" << rec.t << "\n";
        } else {
            std::cout << "FAIL test8: difference A-only t="
                      << rec.t << " expected ~4.134\n";
        }
    }

    /* ----- Test 9: Nested CSG: A - (A intersect B) == A - B ----- */
    {
        total++;
        auto csg_isect = make_shared<csg_node>(sA, sB, csg_op::intersection);
        auto csg_nested = make_shared<csg_node>(sA, csg_isect, csg_op::difference);
        // A - (A & B) = A & ~(A & B) = A & (~A | ~B) = (A&~A) | (A&~B) = A&~B = A-B
        // So first hit should be same as A-B: t = 4.0
        if (csg_nested->hit(r1, interval(0.001, 1e8), rec) && approx(rec.t, 4.0)) {
            passed++;
            std::cout << "PASS test9: nested CSG t=" << rec.t << "\n";
        } else {
            std::cout << "FAIL test9: nested CSG t="
                      << rec.t << " expected 4.0\n";
        }
    }

    /* ----- Test 10: Bounding box validity ----- */
    {
        total++;
        auto csg = make_shared<csg_node>(sA, sB, csg_op::union_op);
        aabb bb = csg->bounding_box();
        // A: [-1,1]^3.  B: [-0.4,1.6] x [-1,1] x [-1,1]
        // Union bbox x: [-1, 1.6]
        if (bb.x.min <= -0.99 && bb.x.max >= 1.59 &&
            bb.y.min <= -0.99 && bb.y.max >= 0.99 &&
            bb.z.min <= -0.99 && bb.z.max >= 0.99) {
            passed++;
            std::cout << "PASS test10: bounding box valid\n";
        } else {
            std::cout << "FAIL test10: bbox x=[" << bb.x.min << "," << bb.x.max
                      << "] y=[" << bb.y.min << "," << bb.y.max
                      << "] z=[" << bb.z.min << "," << bb.z.max << "]\n";
        }
    }

    /* ----- Test 11: Ray originating inside CSG difference solid ----- */
    {
        total++;
        // Origin (-0.5, 0, 0): inside A (dist 0.5 < 1.0), outside B (dist 1.1 > 1.0)
        // So origin IS inside A-B (insideA && !insideB)
        // Direction: (-1, 0, 0)
        // A exit: (-0.5-t)^2 = 1 -> t = 0.5 at point (-1, 0, 0)
        // B: (-1.1-t)^2 = 1 -> t = -0.1 or -2.1, both negative -> no hit
        // CSG boundary: exit A at t=0.5, front_face=false (back face)
        ray r_inside(point3(-0.5, 0, 0), vec3(-1, 0, 0));
        auto csg = make_shared<csg_node>(sA, sB, csg_op::difference);
        if (csg->hit(r_inside, interval(0.001, 1e8), rec) &&
            approx(rec.t, 0.5) && rec.front_face == false) {
            passed++;
            std::cout << "PASS test11: interior ray t=" << rec.t
                      << " front_face=" << rec.front_face << "\n";
        } else {
            std::cout << "FAIL test11: interior ray t=" << rec.t
                      << " expected 0.5 front_face=false, got front_face="
                      << rec.front_face << "\n";
        }
    }

    /* ----- Test 12: Intersection of non-overlapping spheres misses ----- */
    {
        total++;
        // Sphere C at (5,0,0) r=1.0 — does not overlap sphere A at (0,0,0) r=1.0
        auto sC = make_shared<sphere>(point3(5, 0, 0), 1.0, mat);
        auto csg = make_shared<csg_node>(sA, sC, csg_op::intersection);
        // A: [4.0, 6.0], C: [9.0, 11.0] — disjoint intervals
        // Intersection of disjoint solids is empty: must return no hit
        if (!csg->hit(r1, interval(0.001, 1e8), rec)) {
            passed++;
            std::cout << "PASS test12: disjoint intersection misses\n";
        } else {
            std::cout << "FAIL test12: disjoint intersection should miss, hit t="
                      << rec.t << "\n";
        }
    }

    std::cout << "\nPASSED " << passed << "/" << total << "\n";
    if (passed == total) {
        std::cout << "ALL TESTS PASSED\n";
    }
    return (passed == total) ? 0 : 1;
}
