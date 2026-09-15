WarpX Input File Format
========================

WarpX reads input parameters using AMReX's ParmParse module.
The input file uses a key-value format with the following conventions:

- Parameters use dot-separated namespaces: ``amr.n_cell = 32 32 256``
- Multiple values are space-separated on the same line
- Comments begin with ``#`` and extend to end of line
- String values are enclosed in double quotes: ``"NUniformPerCell"``
- Numerical values support scientific notation: ``1.75e24``, ``-30.e-6``

User-Defined Constants
~~~~~~~~~~~~~~~~~~~~~~

Users can define reusable constants with the ``my_constants`` prefix::

    my_constants.n0 = 1.75e24
    my_constants.wp = 7.5e13

These can be referenced by name (without the ``my_constants.`` prefix)
in any numerical parameter elsewhere in the file::

    electrons.density = n0

The constant name alone acts as a reference to the value defined under
``my_constants``. This mechanism allows parameterizing simulation setups
so that derived quantities stay consistent with base values.

WarpX Built-in Constants
~~~~~~~~~~~~~~~~~~~~~~~~

See ``constants.txt`` for the predefined physical constants available
in all numerical expressions within WarpX input files.

Key Parameter Groups
~~~~~~~~~~~~~~~~~~~~

Grid Parameters:
    - ``amr.n_cell``: Number of cells in each direction (space-separated integers)
    - ``geometry.dims``: Number of spatial dimensions (1, 2, or 3)
    - ``geometry.prob_lo``: Lower corner of physical domain (space-separated floats, meters)
    - ``geometry.prob_hi``: Upper corner of physical domain (space-separated floats, meters)

Numerics:
    - ``warpx.cfl``: CFL safety factor (float, typically <= 1)
    - ``algo.particle_shape``: Order of particle shape function (1, 2, or 3)
    - ``algo.maxwell_solver``: Field solver type (default: ``yee``)

Species:
    - ``particles.species_names``: Space-separated list of species names
    - ``<species>.density``: Particle number density (m^-3); may be a literal or a constant reference
    - ``<species>.charge``: Particle charge (use ``q_e``, ``-q_e``, etc.)
    - ``<species>.mass``: Particle mass (use ``m_e``, ``m_p``, or expression)

Laser:
    - ``lasers.names``: Space-separated list of laser names
    - ``<laser>.wavelength``: Laser wavelength (m)
    - ``<laser>.e_max``: Peak electric field amplitude (V/m)
    - ``<laser>.profile_waist``: Beam waist at focus (m)
    - ``<laser>.profile_duration``: Pulse duration (s)
    - ``<laser>.profile_focal_distance``: Focal distance from antenna (m)
