"""
Analytical 1D steady-state conjugate heat transfer solver.

Problem setup:
  Solid heater block with uniform volumetric heat generation q_gen [W/m^3].
  Bottom boundary (y=0): adiabatic wall, dT/dy = 0.
  Top boundary (y=H):   convective interface, q = h*(T_surface - T_fluid).

  Governing ODE: d^2 T / dy^2 = -q_gen / k_s

  Solution approach:
    All heat generated in the solid (q_gen * H per unit area) must exit
    through the top surface since the bottom is adiabatic.
    Interface heat flux: q_flux = q_gen * H
    Interface temperature from Newton cooling: q_flux = h * (T_int - T_f)
    Temperature profile: T(y) = T_int + q_gen/(2*k_s) * (H^2 - y^2)
    Maximum temperature at y=0: T_max = T_int + q_gen*H^2/(2*k_s)
"""


def solve_cht(params, solid_block_id, fluid_interface_block_id):
    """Compute analytical 1D steady-state CHT solution for the heater block.

    Args:
        params: dict with 'thermal_properties' and 'heater_region'
        solid_block_id: index of the solid (heater) block
        fluid_interface_block_id: index of the fluid block above the heater

    Returns:
        dict with solid_block, fluid_interface_block, temperatures, heat flux
    """
    tp = params['thermal_properties']
    k_s = tp['solid_conductivity']
    q_gen = tp['volumetric_heat_generation']
    T_f = tp['fluid_bulk_temperature']
    h_conv = tp['convective_htc']

    heater = params['heater_region']
    H = heater['y_range'][1] - heater['y_range'][0]

    # Total heat flux leaving through the top surface
    q_flux = q_gen * H

    # Interface temperature: Newton's law of cooling
    # q_flux = h_conv * (T_interface - T_f)
    T_interface = T_f - q_flux / h_conv

    # Maximum temperature at the adiabatic bottom wall
    T_max = T_interface + q_gen / (2.0 * k_s) * H ** 2

    return {
        'solid_block': solid_block_id,
        'fluid_interface_block': fluid_interface_block_id,
        'interface_temperature_K': round(T_interface, 4),
        'max_heater_temperature_K': round(T_max, 4),
        'interface_heat_flux_W_m2': round(q_flux, 4),
    }
