"""2D rigid body transforms for coordinate frame management.

"""

import math


class Transform2D:
    """Represents a 2D rigid transform (translation + rotation).

    Convention: transforms a point from the child frame to the parent frame.
    """

    def __init__(self, x, y, theta):
        self.x = x
        self.y = y
        self.theta = theta

    def transform_point(self, px, py):
        """Transform a point from child frame to parent frame."""
        cos_t = math.cos(self.theta)
        sin_t = math.sin(self.theta)
        rx = cos_t * px - sin_t * py + self.x
        ry = sin_t * px + cos_t * py + self.y
        return rx, ry

    def inverse(self):
        """Compute the inverse transform."""
        cos_t = math.cos(-self.theta)
        sin_t = math.sin(-self.theta)
        inv_x = cos_t * (-self.x) - sin_t * (-self.y)
        inv_y = sin_t * (-self.x) + cos_t * (-self.y)
        return Transform2D(inv_x, inv_y, -self.theta)

    def compose(self, other):
        """Compose this transform with another: self * other.

        Result transforms from other's child frame to self's parent frame.
        """
        new_x = self.x + other.x
        new_y = self.y + other.y
        new_theta = self.theta + other.theta
        return Transform2D(new_x, new_y, new_theta)

    def __repr__(self):
        return "Transform2D(x={:.4f}, y={:.4f}, theta={:.4f})".format(
            self.x, self.y, self.theta)
