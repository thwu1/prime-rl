"""Packed-bed pressure drop correlation registry."""

from correlations.viscous_inertial import (
    ergun, kuo_nydegger, tallmadge, jones_krier, carman,
)
from correlations.empirical import hicks, brauer, kta
from correlations.advanced import erdim_akgiray_demir, fahien_schriver
from correlations.native import idelchik, harrison_brunner_hecker
from correlations.wall_corrected import montillet_akkari_comiti

# Registry: (function, accepts_Dt)
CORRELATIONS = {
    "Ergun": (ergun, False),
    "Kuo_Nydegger": (kuo_nydegger, False),
    "Tallmadge": (tallmadge, False),
    "Jones_Krier": (jones_krier, False),
    "Carman": (carman, False),
    "Hicks": (hicks, False),
    "Brauer": (brauer, False),
    "KTA": (kta, False),
    "Erdim_Akgiray_Demir": (erdim_akgiray_demir, False),
    "Fahien_Schriver": (fahien_schriver, False),
    "Idelchik": (idelchik, False),
    "Harrison_Brunner_Hecker": (harrison_brunner_hecker, True),
    "Montillet_Akkari_Comiti": (montillet_akkari_comiti, True),
}
