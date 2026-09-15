# BSDF test configurations for Fresnel verification

DIELECTRIC_CONFIG = {
    'type': 'dielectric',
    'int_ior': 1.5,
    'ext_ior': 1.0,
}

CONDUCTOR_CONFIG = {
    'type': 'conductor',
    'eta': {'type': 'rgb', 'value': [0.183, 0.312, 1.557]},
    'k': {'type': 'rgb', 'value': [3.424, 2.385, 1.893]},
}

ROUGH_DIELECTRIC_CONFIG = {
    'type': 'roughdielectric',
    'int_ior': 1.5,
    'ext_ior': 1.0,
    'alpha': 0.1,
    'distribution': 'beckmann',
}

TEST_ANGLES_DEG = [0, 15, 30, 45, 60, 75, 85]
TIR_TEST_ANGLES_DEG = [0, 20, 30, 40, 41, 41.5, 42, 43, 50, 60, 80]
ROUGH_MC_ANGLE_DEG = 30
MC_SAMPLES = 100000
