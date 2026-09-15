#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Excerpt from groundhog geotechnical library - consolidation module
# Author: Bruno Stuyts
# Reference: Budhu (2011). Soil mechanics and foundation engineering.
#
# NOTE: This file requires numpy, pandas, plotly, and groundhog dependencies
# to run. It is provided as domain reference only.

import numpy as np
from copy import deepcopy


class ConsolidationCalculation(object):
    """
    The consolidation equation can be discretised as follows:

    .. math::
        u_{i,j+1} = u_{i,j} + \\frac{c_v \\Delta t}{(\\Delta z)^2}
            (u_{i-1,j} - 2 u_{i,j} + u_{i+1,j})

    At permeable boundaries, the excess pore pressure is 0 (u = 0).
    At impervious boundaries, the following boundary condition applies:

    .. math::
        \\frac{\\partial u}{\\partial z} = 0
            = \\frac{1}{2 \\Delta z} (u_{i-1,j} - u_{i+1,j}) = 0

        \\implies u_{i,j+1} = u_{i,j} + \\frac{c_v \\Delta t}{(\\Delta z)^2}
            (2 u_{i-1,j} - 2 u_{i,j})

    To ensure stability, the timestep needs to be chosen according to:

    .. math::
        \\alpha = \\frac{c_v \\Delta t}{(\\Delta z)^2} < \\frac{1}{2}

    Usually, alpha = 0.25 is used to determine the timestep.
    """

    def __init__(self, height, total_time, no_nodes):
        """
        Initialises the consolidation calculation with the height of the layer
        and the total time. Subdivision of the height in m elements is performed.
        """
        self.m = no_nodes
        self.H0 = height
        self.T = total_time
        self.z = np.linspace(0, height, no_nodes)
        self.dz = np.diff(self.z)[0]

    def set_cv(self, cv, uniform=True, cv_depths=None):
        """
        Sets the coefficient of consolidation. cv is specified in m2/yr
        and is converted to m2/s inside the routine (all calcs happen in s).
        """
        if uniform:
            self.cv = np.ones(self.z.__len__()) * cv / (365 * 24 * 3600)
            self.cv_depths = None
        else:
            cv_depths = np.array(cv_depths)
            cv = np.array(cv)
            self.cv = np.interp(self.z, cv_depths, cv / (365 * 24 * 3600))

        self.dt = 0.25 * (self.dz ** 2) / self.cv.max()
        self.n = int(np.ceil(self.T / self.dt))
        self.times = np.linspace(0, self.T, self.n + 1)

    def set_top_boundary(self, freedrainage=True):
        """
        Sets the boundary condition at the top.
        Set freedrainage=False for an impervious top surface.
        """
        if freedrainage:
            self.top_boundary = "open"
        else:
            self.top_boundary = "closed"

    def set_bottom_boundary(self, freedrainage=True):
        """
        Sets the boundary condition at the bottom.
        Set freedrainage=False for an impervious bottom surface.
        """
        if freedrainage:
            self.bottom_boundary = "open"
        else:
            self.bottom_boundary = "closed"

    def set_initial(self, u0, u0_depths):
        """
        Sets the initial excess pore pressure distribution.
        """
        if u0.__len__() != u0_depths.__len__():
            raise ValueError(
                "Array with excess pore pressures and corresponding depths "
                "need to be of equal length")
        self.u0 = np.interp(self.z, u0_depths, u0)

    def set_output_times(self, output_times):
        """
        Sets the times at which output is requested.
        These are pasted into the array with computed times.
        """
        self.times = np.unique(np.sort(np.append(self.times, output_times)))
        self.dts = np.diff(self.times)
        self.output_times = output_times
        self.output_indices = []
        for _t in self.output_times:
            self.output_indices.append(np.where(self.times == _t)[0][0])

    def calculate(self):
        """
        Calculates the pore pressure dissipation until the specified output time.
        """
        u = deepcopy(self.u0)
        self.u_steps = []
        self.u_steps.append(u)
        for j, _dt in enumerate(self.dts):
            u_previous = deepcopy(u)
            u = np.zeros(self.m)
            for i, _z in enumerate(self.z):
                if i == 0:
                    if self.top_boundary == "open":
                        u[i] = 0
                    elif self.top_boundary == "closed":
                        u[i] = u_previous[i] + ((self.cv[i] * _dt) / (self.dz ** 2)) * \
                            (-2 * u_previous[i] + 2 * u_previous[i + 1])
                elif i == self.m - 1:
                    if self.bottom_boundary == "open":
                        u[i] = 0
                    elif self.bottom_boundary == "closed":
                        u[i] = u_previous[i] + ((self.cv[i] * _dt) / (self.dz ** 2)) * \
                            (2 * u_previous[i - 1] - 2 * u_previous[i])
                else:
                    u[i] = u_previous[i] + ((self.cv[i] * _dt) / (self.dz ** 2)) * \
                        (u_previous[i - 1] - 2 * u_previous[i] + u_previous[i + 1])
            self.u_steps.append(u)
