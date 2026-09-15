#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
CI2 Strong Vortex-Shock Wave Interaction - Initial Condition Generator
HiOCFD5 - 5th International Workshop on High-Order CFD Methods

Generates the initial condition for the CI2 benchmark:
a strong vortex (Mv=0.9) interacting with a stationary normal shock (Ms=1.5).

Original Python 2 implementation from workshop distribution.
"""

import math


class CI2InitCondition:
    """Generator for the CI2 vortex-shock initial condition.

    Physical setup:
      - Domain: [0, 1] x [0, 1]
      - Stationary normal shock at x = 0.5
      - Upstream (x <= 0.5): rho=1, p=1, u = Ms * sqrt(gamma)
      - Downstream: Rankine-Hugoniot jump conditions
      - Vortex center at (0.25, 0.5), inner radius a=0.075, outer radius b=0.175
      - Vortex Mach number Mv = 0.9
    """

    def __init__(self, gamma=1.4, gas_const=1.0, M_shock=1.5, M_vortex=0.9):
        self.g = gamma
        self.R = gas_const
        self.M_s = M_shock
        self.M_v = M_vortex

        # Upstream conditions
        self.rho_u = 1.0
        self.u_u = self.M_s * math.sqrt(self.g)
        self.v_u = 1.0E-20
        self.w_u = 1.0E-20
        self.p_u = 1.0
        self.t_u = self.p_u / (self.rho_u * self.R)

        # Downstream conditions via Rankine-Hugoniot
        self.rho_d = self.rho_u * (self.g + 1) * self.M_s ** 2 / \
                     (2.0 + (self.g - 1) * self.M_s ** 2)
        self.u_d = self.u_u * (2.0 + (self.g - 1) * self.M_s ** 2) / \
                   ((self.g + 1) * self.M_s ** 2)
        self.v_d = self.v_u
        self.w_d = self.w_u
        self.p_d = self.p_u * (1.0 + (2.0 * self.g / (self.g + 1.0)) *
                               (self.M_s ** 2 - 1.0))

        # Vortex parameters
        self.x_c = 0.25
        self.y_c = 0.5
        self.a = 0.075   # inner core radius
        self.b = 0.175   # outer vortex radius
        self.v_m = self.M_v * math.sqrt(self.g)

    def evaluate(self, x, y):
        """Evaluate initial condition at point (x, y).

        Returns dict with pressure, temperature, velocity (3-tuple).
        """
        location = [x, y, 0.0]

        # Base state: upstream or downstream of shock
        if location[0] <= 0.5:
            pressure = self.p_u
            temperature = self.t_u
            velocity = [self.u_u, self.v_u, self.w_u]
        else:
            pressure = self.p_d
            temperature = self.p_d / (self.rho_d * self.R)
            velocity = [self.u_d, self.v_d, self.w_d]

        # Distance from vortex center
        dx = location[0] - self.x_c
        dy = location[1] - self.y_c
        r = math.sqrt(dx * dx + dy * dy)

        # Superimpose vortex (only within outer radius b)
        if r <= self.b and r > 0:

            sin_theta = dy / r
            cos_theta = dx / r

            if r <= self.a:
                # Inner core: solid body rotation
                mag = self.v_m * r / self.a
                velocity[0] = velocity[0] - mag * sin_theta
                velocity[1] = velocity[1] + mag * cos_theta

                # Temperature at inner radius a (from below)
                radial_term = (-2.0 * self.b ** 2 * math.log(self.b)
                               - 0.5 * self.a ** 2
                               + 2.0 * self.b ** 2 * math.log(self.a)
                               + 0.5 * self.b ** 4 / self.a ** 2)
                t_a = self.t_u - ((self.g - 1.0) *
                      math.pow(self.v_m * self.a / (self.a ** 2 - self.b ** 2), 2) *
                      radial_term / (self.R * self.g))
                radial_term_inner = 0.5 * (1.0 - r ** 2 / self.a ** 2)
                temperature = t_a - ((self.g - 1.0) * self.v_m ** 2 *
                              radial_term_inner / (self.R * self.g))
            else:
                # Outer annulus: irrotational vortex
                mag = self.v_m * self.a * (r - self.b ** 2 / r) / \
                      (self.a ** 2 - self.b ** 2)
                velocity[0] = velocity[0] - mag * sin_theta
                velocity[1] = velocity[1] + mag * cos_theta

                # Temperature via isentropic relation
                radial_term = (-2.0 * self.b ** 2 * math.log(self.b)
                               - 0.5 * r ** 2
                               + 2.0 * self.b ** 2 * math.log(r)
                               + 0.5 * self.b ** 4 / r ** 2)
                temperature = self.t_u - ((self.g - 1.0) *
                              math.pow(self.v_m * self.a / (self.a ** 2 - self.b ** 2), 2) *
                              radial_term / (self.R * self.g))

            pressure = self.p_u * math.pow(temperature / self.t_u,
                                           self.g / (self.g - 1.0))

        return {'pressure': pressure, 'temperature': temperature,
                'velocity': tuple(velocity)}


def compute_entropy(pressure, density, gamma=1.4):
    """Compute specific entropy s = p / rho^gamma (normalized)."""
    return pressure / density ** gamma


def compute_mach(velocity, pressure, density, gamma=1.4):
    """Compute local Mach number."""
    speed_sq = sum(v ** 2 for v in velocity)
    a = math.sqrt(gamma * pressure / density)
    return math.sqrt(speed_sq) / a


if __name__ == '__main__':
    ic = CI2InitCondition()

    # Test at a few representative points
    test_points = [(0.1, 0.5), (0.25, 0.5), (0.6, 0.5), (0.2, 0.55)]

    print "CI2 Vortex-Shock Initial Condition"
    print "=" * 60

    for pt in test_points:
        result = ic.evaluate(pt[0], pt[1])
        print "\nPoint (%g, %g):" % (pt[0], pt[1])
        print "  pressure    = %g" % result['pressure']
        print "  temperature = %g" % result['temperature']
        print "  velocity    = (%g, %g, %g)" % result['velocity']

        # Compute density from ideal gas law
        rho = result['pressure'] / (ic.R * result['temperature'])
        print "  density     = %g" % rho
        print "  entropy     = %g" % compute_entropy(result['pressure'], rho, ic.g)
        print "  Mach        = %g" % compute_mach(result['velocity'],
                                                   result['pressure'], rho, ic.g)

    # Grid evaluation
    nx = 50
    ny = 50
    print "\nEvaluating on %d x %d grid..." % (nx, ny)

    total_mass = 0.0
    dx_grid = 1.0 / (nx - 1)
    dy_grid = 1.0 / (ny - 1)
    for i in xrange(nx):
        for j in xrange(ny):
            x = float(i) / (nx - 1)
            y = float(j) / (ny - 1)
            result = ic.evaluate(x, y)
            rho = result['pressure'] / (ic.R * result['temperature'])
            total_mass += rho * dx_grid * dy_grid

    print "Grid evaluation complete."
    print "Integrated mass = %g" % total_mass

    # Check dict method (Python 2 idiom)
    test_result = ic.evaluate(0.3, 0.5)
    if test_result.has_key('pressure'):
        print "Pressure field present: %g" % test_result['pressure']
