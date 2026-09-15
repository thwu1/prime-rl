"""
Corrected IAPWS-IF97 wrapper with transport properties.

"""

import ctypes
import os
import math

class IF97PropsStruct(ctypes.Structure):
    _fields_ = [
        ("v", ctypes.c_double), ("h", ctypes.c_double),
        ("u", ctypes.c_double), ("s", ctypes.c_double),
        ("cp", ctypes.c_double), ("w", ctypes.c_double),
        ("p", ctypes.c_double),
    ]

class IF97Engine:
    def __init__(self, lib_path=None):
        if lib_path is None:
            lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libif97.so')
        self.lib = ctypes.CDLL(lib_path)
        self._setup_signatures()

    def _setup_signatures(self):
        self.lib.region1_props.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.region1_props.restype = IF97PropsStruct
        self.lib.region2_props.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.region2_props.restype = IF97PropsStruct
        self.lib.region3_props.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.region3_props.restype = IF97PropsStruct
        self.lib.region5_props.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.region5_props.restype = IF97PropsStruct
        self.lib.saturation_pressure.argtypes = [ctypes.c_double]
        self.lib.saturation_pressure.restype = ctypes.c_double
        self.lib.saturation_temperature.argtypes = [ctypes.c_double]
        self.lib.saturation_temperature.restype = ctypes.c_double
        self.lib.determine_region.argtypes = [ctypes.c_double, ctypes.c_double]
        self.lib.determine_region.restype = ctypes.c_int

    def _to_dict(self, s):
        return {"v": s.v, "h": s.h, "u": s.u, "s": s.s,
                "cp": s.cp, "w": s.w, "p": s.p}

    def region1_props(self, T, p):
        return self._to_dict(self.lib.region1_props(T, p))

    def region2_props(self, T, p):
        return self._to_dict(self.lib.region2_props(T, p))

    def region3_props(self, T, rho):
        return self._to_dict(self.lib.region3_props(T, rho))

    def region5_props(self, T, p):
        return self._to_dict(self.lib.region5_props(T, p))

    def saturation_pressure(self, T):
        return self.lib.saturation_pressure(T)

    def saturation_temperature(self, p):
        return self.lib.saturation_temperature(p)

    def determine_region(self, T, p):
        return self.lib.determine_region(T, p)

    # ================================================================
    # Backward T(p,h) equations
    # ================================================================
    _B1H = [
        (0,0,-238.72489924521),(0,1,404.21188637945),
        (0,2,113.49746881718),(0,6,-5.8457616048039),
        (0,22,-0.00015285482413140),(0,32,-1.0866707695377e-06),
        (1,0,-13.391744872602),(1,1,43.211039183559),
        (1,2,-54.010067170506),(1,3,30.535892203916),
        (1,4,-6.5964749423638),(1,10,0.0093965400878363),
        (1,32,1.1573647505340e-07),(2,10,-0.000025858641282073),
        (2,32,-4.0644363084799e-09),(3,10,6.6456186191635e-08),
        (3,32,8.0670734103027e-11),(4,32,-9.3477771213947e-13),
        (5,32,5.8265442020601e-15),(6,32,-1.5020185953503e-17),
    ]

    _B2aH = [
        (0,0,1089.8952318288),(0,1,849.51654495535),
        (0,2,-107.81748091826),(0,3,33.153654801263),
        (0,7,-7.4232016790248),(0,20,11.765048724356),
        (1,0,1.8445749355790),(1,1,-4.1792700549624),
        (1,2,6.2478196935812),(1,3,-17.344563108114),
        (1,7,-200.58176862096),(1,9,271.96065473796),
        (1,11,-455.11318285818),(1,18,3091.9688604755),
        (1,44,252264.0357872),(2,0,-0.0061707422868339),
        (2,2,-0.31078046629583),(2,7,11.670873077107),
        (2,36,128127984.04046),(2,38,-985549096.23276),
        (2,40,2822454697.3002),(2,42,-3594897141.0703),
        (2,44,1722734991.3197),(3,24,-13551.334240775),
        (3,44,12848734.664650),(4,12,1.3865724283226),
        (4,32,235988.32556514),(4,44,-13105236.545054),
        (5,32,7399.9835474766),(5,36,-551966.97030060),
        (5,42,3715408.5996233),(6,34,19127.729239660),
        (6,44,-415351.64835634),(7,28,-62.459855192507),
    ]

    _B2bH = [
        (0,0,1489.5041079516),(0,1,743.07798314034),
        (0,2,-97.708318797837),(0,12,2.4742464705674),
        (0,18,-0.63281320016026),(0,24,1.1385952129658),
        (0,28,-0.47811863648625),(0,40,0.0085208123431544),
        (1,0,0.93747147377932),(1,2,3.3593118604916),
        (1,6,3.3809355601454),(1,12,0.16844539671904),
        (1,18,0.73875745236695),(1,24,-0.47128737436186),
        (1,28,0.15020273139707),(1,40,-0.0021764114219750),
        (2,2,-0.021810755324761),(2,8,-0.10829784403677),
        (2,18,-0.046333324635812),(2,40,0.000071280351959551),
        (3,1,0.00011032831789999),(3,2,0.00018955248387902),
        (3,12,0.0030891541160537),(3,24,0.0013555504554949),
        (4,2,2.8640237477456e-07),(4,12,-1.0779857357512e-05),
        (4,18,-7.6462712454814e-05),(4,24,1.4052392818316e-05),
        (4,28,-3.1083814331434e-05),(4,40,-1.0302738212103e-06),
        (5,18,2.8217281635040e-07),(5,24,1.2704902271945e-06),
        (5,40,7.3803353468292e-08),(6,28,-1.1030139238909e-08),
        (7,2,-8.1456365207833e-14),(7,28,-2.5180545682962e-11),
        (9,1,-1.7565233969407e-18),(9,40,8.6934156344163e-15),
    ]

    _B2cH = [
        (-7,0,-0.32368398555242e13),(-7,4,0.73263350902181e13),
        (-6,0,0.35825089945447e12),(-6,2,-0.58340131851590e12),
        (-5,0,-0.10783068217470e11),(-5,2,0.20825544563171e11),
        (-2,0,0.61074783564516e6),(-2,1,0.85977722535580e6),
        (-1,0,-0.25745723604170e5),(-1,2,0.31081088422714e5),
        (0,0,0.12082315865936e4),(0,1,0.48219755109255e3),
        (1,4,0.37966001272486e1),(1,8,-0.10842984880077e2),
        (2,4,-0.45364172676660e-1),(6,0,0.14559115658698e-12),
        (6,1,0.11261597407230e-11),(6,4,-0.17804982240686e-10),
        (6,10,0.12324579690832e-6),(6,12,-0.11606921130984e-5),
        (6,16,0.27846367088554e-4),(6,20,-0.59270038474176e-3),
        (6,22,0.12918582991878e-2),
    ]

    _nb2bc = [905.84278514723, -0.67955786399241, 0.00012809002730136,
              2652.6571908428, 4.5257578905948]

    def _h_b2bc(self, p):
        n = self._nb2bc
        return n[3] + math.sqrt((p - n[4]) / n[2])

    def backward_T_ph_region1(self, p, h):
        eta = h / 2500.0
        return sum(n * p**I * (eta + 1.0)**J for I, J, n in self._B1H)

    def backward_T_ph_region2(self, p, h):
        if p <= 4.0:
            eta = h / 2000.0
            return sum(n * p**I * (eta - 2.1)**J for I, J, n in self._B2aH)
        hb = self._h_b2bc(p)
        if h >= hb:
            eta = h / 2000.0
            return sum(n * (p - 2.0)**I * (eta - 2.6)**J for I, J, n in self._B2bH)
        else:
            eta = h / 2000.0
            return sum(n * (p + 25.0)**I * (eta - 1.8)**J for I, J, n in self._B2cH)

    # ================================================================
    # Transport: Viscosity IAPWS 2008
    # ================================================================
    _mu_H0 = [1.67752, 2.20462, 0.6366564, -0.241605]
    _mu_Hr = [
        (0,0,5.20094e-1),(1,0,8.50895e-2),(2,0,-1.08374),(3,0,-2.89555e-1),
        (0,1,2.22531e-1),(1,1,9.99115e-1),(2,1,1.88797),(3,1,1.26613),
        (5,1,1.20573e-1),(0,2,-2.81378e-1),(1,2,-9.06851e-1),(2,2,-7.72479e-1),
        (3,2,-4.89837e-1),(4,2,-2.57040e-1),(0,3,1.61913e-1),(1,3,2.57399e-1),
        (0,4,-3.25372e-2),(3,4,6.98452e-2),(4,5,8.72102e-3),(3,6,-4.35673e-3),
        (5,6,-5.93264e-4),
    ]

    def viscosity(self, rho, T):
        Tc = 647.096; rhoc = 322.0
        Tr = T / Tc; Dr = rho / rhoc
        denom = sum(H / Tr**i for i, H in enumerate(self._mu_H0))
        mu0 = 100.0 * math.sqrt(Tr) / denom
        exp_arg = sum((1.0/Tr - 1.0)**i * h * (Dr - 1.0)**j
                      for i, j, h in self._mu_Hr)
        mu1 = math.exp(Dr * exp_arg)
        return mu0 * mu1 * 1e-6

    # ================================================================
    # Transport: Thermal Conductivity IAPWS 2011 (lambda2=0)
    # ================================================================
    _lam_L0 = [2.443221e-3, 1.323095e-2, 6.770357e-3, -3.454586e-3, 4.096266e-4]
    _lam_Lr = [
        (0,0,1.60397357),(0,1,-0.646013523),(0,2,0.111443906),
        (0,3,0.102997357),(0,4,-0.0504123634),(0,5,0.00609859258),
        (1,0,2.33771842),(1,1,-2.78843778),(1,2,1.53616167),
        (1,3,-0.463045512),(1,4,0.0832827019),(1,5,-0.00719201245),
        (2,0,2.19650529),(2,1,-4.54580785),(2,2,3.55777244),
        (2,3,-1.40944978),(2,4,0.275418278),(2,5,-0.0205938816),
        (3,0,-1.21051378),(3,1,1.60812989),(3,2,-0.621178141),
        (3,3,0.0716373224),
        (4,0,-2.7203370),(4,1,4.57586331),(4,2,-3.18369245),
        (4,3,1.1168348),(4,4,-0.19268305),(4,5,0.012913842),
    ]

    def thermal_conductivity(self, rho, T):
        Tc = 647.096; rhoc = 322.0
        d = rho / rhoc; Tr = T / Tc
        denom = sum(L / Tr**i for i, L in enumerate(self._lam_L0))
        k0 = math.sqrt(Tr) / denom
        exp_arg = sum((1.0/Tr - 1.0)**i * L * (d - 1.0)**j
                      for i, j, L in self._lam_Lr)
        k1 = math.exp(d * exp_arg)
        return k0 * k1 * 1e-3
