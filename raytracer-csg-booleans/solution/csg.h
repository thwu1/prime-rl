#ifndef CSG_H
#define CSG_H
/*
 *
 * Constructive Solid Geometry (CSG) for the ray tracer.
 * Supports union, intersection, and difference of any hittable objects.
 */

#include "hittable.h"

#include <vector>
#include <algorithm>

enum class csg_op {
    union_op,
    intersection,
    difference
};

class csg_node : public hittable {
  public:
    csg_node(shared_ptr<hittable> left, shared_ptr<hittable> right, csg_op op)
      : left(left), right(right), op(op)
    {
        aabb lb = left->bounding_box();
        aabb rb = right->bounding_box();
        switch (op) {
            case csg_op::union_op:
            case csg_op::intersection:
                bbox = aabb(lb, rb);
                break;
            case csg_op::difference:
                bbox = lb;
                break;
        }
    }

    aabb bounding_box() const override { return bbox; }

    bool hit(const ray& r, interval ray_t, hit_record& rec) const override {
        if (!bbox.hit(r, ray_t))
            return false;

        // Collect every surface crossing with both children.
        std::vector<crossing> xings;
        collect(*left,  r, ray_t, true,  xings);
        collect(*right, r, ray_t, false, xings);

        if (xings.empty())
            return false;

        // Sort by parameter t.
        std::sort(xings.begin(), xings.end(),
                  [](const crossing& a, const crossing& b) { return a.t < b.t; });

        // Determine the initial inside/outside state for each child.
        // If the first hit on a child is a back-face hit (front_face == false),
        // the ray origin is inside that child.
        bool in_left  = false;
        bool in_right = false;
        for (const auto& x : xings) {
            if (x.is_left) { in_left = !x.rec.front_face; break; }
        }
        for (const auto& x : xings) {
            if (!x.is_left) { in_right = !x.rec.front_face; break; }
        }

        bool prev = eval(in_left, in_right);

        // Walk through crossings; look for a CSG boundary transition.
        for (const auto& x : xings) {
            if (x.is_left)
                in_left = !in_left;
            else
                in_right = !in_right;

            bool curr = eval(in_left, in_right);

            if (curr != prev && ray_t.surrounds(x.t)) {
                rec = x.rec;

                // For difference through the right (subtracted) child the CSG
                // solid's outward normal is opposite to the child's.  Flipping
                // front_face (without touching the stored normal direction)
                // keeps the set_face_normal convention intact:
                //   front_face == true  =>  stored normal IS the outward normal
                //   front_face == false =>  stored normal is -outward normal
                if (op == csg_op::difference && !x.is_left)
                    rec.front_face = !x.rec.front_face;

                return true;
            }

            prev = curr;
        }

        return false;
    }

  private:
    shared_ptr<hittable> left;
    shared_ptr<hittable> right;
    csg_op op;
    aabb   bbox;

    // A single ray-surface crossing.
    struct crossing {
        double     t;
        hit_record rec;
        bool       is_left;
    };

    // Enumerate every surface hit by repeatedly querying the child.
    static void collect(const hittable& obj, const ray& r, interval ray_t,
                        bool is_left, std::vector<crossing>& out) {
        double t_start = ray_t.min;
        int safety = 0;
        while (t_start < ray_t.max && safety < 64) {
            hit_record rec;
            if (obj.hit(r, interval(t_start, ray_t.max), rec)) {
                out.push_back({rec.t, rec, is_left});
                t_start = rec.t + 1e-4;
                safety++;
            } else {
                break;
            }
        }
    }

    // Evaluate the CSG boolean predicate.
    bool eval(bool l, bool r) const {
        switch (op) {
            case csg_op::union_op:     return l || r;
            case csg_op::intersection: return l && r;
            case csg_op::difference:   return l && !r;
        }
        return false;
    }
};

#endif
