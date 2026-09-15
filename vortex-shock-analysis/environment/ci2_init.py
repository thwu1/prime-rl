"""Flow state initialization for a 2D compressible flow configuration."""
import math


def flow_state(x, y):
    """Return local flow state at coordinates (x, y) in domain [0,1]x[0,1].

    Returns dict with keys 'pressure', 'temperature', 'velocity' (3-tuple).
    Gas model: ideal gas, gamma=1.4, R=1.
    """
    g = 1.4
    R = 1.0

    rho_1 = 1.0
    u_1 = 1.5 * math.sqrt(g)
    p_1 = 1.0
    t_1 = p_1 / (rho_1 * R)

    M_s = 1.5

    rho_2 = rho_1 * (g + 1.0) * M_s**2 / (2.0 + (g - 1.0) * M_s**2)
    u_2 = u_1 * (2.0 + (g - 1.0) * M_s**2) / ((g + 1.0) * M_s**2)
    p_2 = p_1 * (1.0 + (2.0 * g / (g + 1.0)) * (M_s**2 - 1.0))

    pressure = p_1
    temperature = t_1
    velocity = [u_1, 1.0e-20, 0.0]

    if x > 0.5:
        pressure = p_2
        temperature = p_2 / (rho_2 * R)
        velocity[0] = u_2

    x_c, y_c = 0.25, 0.5
    a = 0.075
    b = 0.175
    M_v = 0.9
    v_m = M_v * math.sqrt(g)

    dx = x - x_c
    dy = y - y_c
    r = math.sqrt(dx**2 + dy**2)

    if r <= b and x <= 0.5:
        if r > 1e-15:
            sin_theta = dy / r
            cos_theta = dx / r
        else:
            sin_theta = 0.0
            cos_theta = 0.0

        if r <= a and r > 1e-15:
            mag = v_m * r / a
            velocity[0] -= mag * sin_theta
            velocity[1] += mag * cos_theta

            rt_bnd = (
                -2.0 * b**2 * math.log(b)
                - 0.5 * a**2
                + 2.0 * b**2 * math.log(a)
                + 0.5 * b**4 / a**2
            )
            t_bnd = t_1 - (g - 1.0) * (v_m * a / (a**2 - b**2)) ** 2 * rt_bnd / (R * g)
            rt_loc = 0.5 * (1.0 - r**2 / a**2)
            temperature = t_bnd - (g - 1.0) * v_m**2 * rt_loc / (R * g)

        elif r <= a:
            rt_bnd = (
                -2.0 * b**2 * math.log(b)
                - 0.5 * a**2
                + 2.0 * b**2 * math.log(a)
                + 0.5 * b**4 / a**2
            )
            t_bnd = t_1 - (g - 1.0) * (v_m * a / (a**2 - b**2)) ** 2 * rt_bnd / (R * g)
            temperature = t_bnd - (g - 1.0) * v_m**2 * 0.5 / (R * g)

        else:
            mag = v_m * a * (r - b**2 / r) / (a**2 - b**2)
            velocity[0] -= mag * sin_theta
            velocity[1] += mag * cos_theta

            rt_loc = (
                -2.0 * b**2 * math.log(b)
                - 0.5 * r**2
                + 2.0 * b**2 * math.log(r)
                + 0.5 * b**4 / r**2
            )
            temperature = t_1 - (g - 1.0) * (v_m * a / (a**2 - b**2)) ** 2 * rt_loc / (R * g)

        pressure = p_1 * (temperature / t_1) ** (g / (g - 1.0))

    return {"pressure": pressure, "temperature": temperature, "velocity": tuple(velocity)}
