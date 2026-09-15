#!/usr/bin/env python3
"""
IAPWS-IF97 CLI using C shared library for Regions 1, 2, saturation,
and pure Python for Region 3, Region 5, and backward equations.

"""

import sys
import math
import ctypes

R = 0.461526
Tc = 647.096
Pc = 22.064
rhoc = 322.0

# ===== Load C shared library =====
_lib = ctypes.CDLL("/app/src/libif97.so")

_lib.if97_gamma1.restype = None
_lib.if97_gamma1.argtypes = [
    ctypes.c_double, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)
]

_lib.if97_gamma2_ideal.restype = None
_lib.if97_gamma2_ideal.argtypes = [
    ctypes.c_double, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double)
]

_lib.if97_gamma2_res.restype = None
_lib.if97_gamma2_res.argtypes = [
    ctypes.c_double, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)
]

_lib.if97_psat_t.restype = ctypes.c_double
_lib.if97_psat_t.argtypes = [ctypes.c_double]

_lib.if97_tsat_p.restype = ctypes.c_double
_lib.if97_tsat_p.argtypes = [ctypes.c_double]

_lib.if97_p23_t.restype = ctypes.c_double
_lib.if97_p23_t.argtypes = [ctypes.c_double]


def PSat_T(T):
    return _lib.if97_psat_t(T)

def TSat_P(P):
    return _lib.if97_tsat_p(P)

def P23_T(T):
    return _lib.if97_p23_t(T)


def _hbc_P(P):
    return 0.26526571908428e+04 + ((P - 4.5257578905948) / 1.2809002730136e-4)**0.5


def region_TP(T, P):
    if 1073.15 < T <= 2273.15 and 0 < P <= 50:
        return 5
    if T > 1073.15:
        return -1
    if 273.15 <= T <= 623.15:
        ps = PSat_T(T)
        return 1 if P >= ps else 2
    if 623.15 < T <= 1073.15:
        p23 = P23_T(T)
        return 2 if P <= p23 else 3
    return -1


# ===== Region 1 (via C library) =====
def Region1(T, P):
    tau = 1386.0 / T
    pi = P / 16.53
    g = ctypes.c_double()
    gp = ctypes.c_double()
    gpp = ctypes.c_double()
    gt = ctypes.c_double()
    gtt = ctypes.c_double()
    gpt = ctypes.c_double()
    _lib.if97_gamma1(pi, tau,
                     ctypes.byref(g), ctypes.byref(gp), ctypes.byref(gpp),
                     ctypes.byref(gt), ctypes.byref(gtt), ctypes.byref(gpt))
    g, gp, gpp = g.value, gp.value, gpp.value
    gt, gtt, gpt = gt.value, gtt.value, gpt.value

    v = pi * gp * R * T / P / 1000
    h = tau * gt * R * T
    s = R * (tau * gt - g)
    cp = -R * tau**2 * gtt
    cv = R * (-tau**2 * gtt + (gp - tau * gpt)**2 / gpp)
    w = (R * T * 1000 * gp**2 / ((gp - tau * gpt)**2 / (tau**2 * gtt) - gpp))**0.5
    u = h - P * 1000 * v
    return v, h, u, s, cp, cv, w


# ===== Region 2 (via C library) =====
def Region2(T, P):
    tau = 540.0 / T
    pi = P
    g0 = ctypes.c_double()
    g0p = ctypes.c_double()
    g0pp = ctypes.c_double()
    g0t = ctypes.c_double()
    g0tt = ctypes.c_double()
    _lib.if97_gamma2_ideal(pi, tau,
                           ctypes.byref(g0), ctypes.byref(g0p), ctypes.byref(g0pp),
                           ctypes.byref(g0t), ctypes.byref(g0tt))
    gr = ctypes.c_double()
    grp = ctypes.c_double()
    grpp = ctypes.c_double()
    grt = ctypes.c_double()
    grtt = ctypes.c_double()
    grpt = ctypes.c_double()
    _lib.if97_gamma2_res(pi, tau,
                         ctypes.byref(gr), ctypes.byref(grp), ctypes.byref(grpp),
                         ctypes.byref(grt), ctypes.byref(grtt), ctypes.byref(grpt))
    go = g0.value
    gop = g0p.value
    gopp = g0pp.value
    got = g0t.value
    gott = g0tt.value
    grv = gr.value
    grpv = grp.value
    grppv = grpp.value
    grtv = grt.value
    grttv = grtt.value
    grptv = grpt.value

    v = pi * (gop + grpv) * R * T / P / 1000
    h = tau * (got + grtv) * R * T
    s = R * (tau * (got + grtv) - (go + grv))
    cp = -R * tau**2 * (gott + grttv)
    cv = R * (-tau**2 * (gott + grttv) - (1 + pi * grpv - tau * pi * grptv)**2 / (1 - pi**2 * grppv))
    w = (R * T * 1000 * (1 + 2 * pi * grpv + pi**2 * grpv**2) /
         (1 - pi**2 * grppv + (1 + pi * grpv - tau * pi * grptv)**2 / tau**2 / (gott + grttv)))**0.5
    u = h - P * 1000 * v
    return v, h, u, s, cp, cv, w


# ===== Region 3 (pure Python) =====
R3_n1 = 1.0658070028513e+00
R3_I = [0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,2,2,3,3,3,3,3,4,4,4,4,5,5,5,6,6,6,7,8,9,9,10,10,11]
R3_J = [0,1,2,7,10,12,23,2,6,15,17,0,2,6,7,22,26,0,2,4,16,26,0,2,4,26,1,3,26,0,2,26,2,26,2,26,0,1,26]
R3_n = [
   -0.15732845290239e+02,  0.20944396974307e+02, -0.76867707878716e+01,
    0.26185947787954e+01, -0.28080781148620e+01,  0.12053369696517e+01,
   -0.84566812812502e-02, -0.12654315477714e+01, -0.11524407806681e+01,
    0.88521043984318e+00, -0.64207765181607e+00,  0.38493460186671e+00,
   -0.85214708824206e+00,  0.48972281541877e+01, -0.30502617256965e+01,
    0.39420536879154e-01,  0.12558408424308e+00, -0.27999329698710e+00,
    0.13899799569460e+01, -0.20189915023570e+01, -0.82147637173963e-02,
   -0.47596035734923e+00,  0.43984074473500e-01, -0.44476435428739e+00,
    0.90572070719733e+00,  0.70522450087967e+00,  0.10770512626332e+00,
   -0.32913623258954e+00, -0.50871062041158e+00, -0.22175400873096e-01,
    0.94260751665092e-01,  0.16436278447961e+00, -0.13503372241348e-01,
   -0.14834345352472e-01,  0.57922953628084e-03,  0.32308904703711e-02,
    0.80964802996215e-04, -0.16557679795037e-03, -0.44923899061815e-04]

def _region3_pressure(rho, T):
    delta = rho / rhoc
    tau = Tc / T
    gd = R3_n1 / delta
    for k in range(39):
        Ik = R3_I[k]
        Jk = R3_J[k]
        nk = R3_n[k]
        if Ik != 0:
            gd += nk * Ik * delta**(Ik - 1) * tau**Jk
    return delta * gd * rho * R * T / 1000

def Region3_rhoT(rho, T):
    delta = rho / rhoc
    tau = Tc / T
    g = R3_n1 * math.log(delta)
    gd = R3_n1 / delta
    gdd = -R3_n1 / delta**2
    gt = 0.0
    gtt = 0.0
    gdt = 0.0
    for k in range(39):
        Ik = R3_I[k]
        Jk = R3_J[k]
        nk = R3_n[k]
        d_Ik = delta**Ik
        t_Jk = tau**Jk
        g += nk * d_Ik * t_Jk
        if Ik >= 1:
            gd += nk * Ik * delta**(Ik - 1) * t_Jk
            if Ik >= 2:
                gdd += nk * Ik * (Ik - 1) * delta**(Ik - 2) * t_Jk
        if Jk >= 1:
            gt += nk * Jk * d_Ik * tau**(Jk - 1)
            if Jk >= 2:
                gtt += nk * Jk * (Jk - 1) * d_Ik * tau**(Jk - 2)
        if Ik >= 1 and Jk >= 1:
            gdt += nk * Ik * Jk * delta**(Ik - 1) * tau**(Jk - 1)
    P_calc = delta * gd * rho * R * T / 1000
    v = 1.0 / rho
    h = R * T * (tau * gt + delta * gd)
    s = R * (tau * gt - g)
    cp = R * (-tau**2 * gtt + (delta * gd - delta * tau * gdt)**2 / (2 * delta * gd + delta**2 * gdd))
    cv = -R * tau**2 * gtt
    w = (R * T * 1000 * (2 * delta * gd + delta**2 * gdd - (delta * gd - delta * tau * gdt)**2 / tau**2 / gtt))**0.5
    u = h - P_calc * 1000 * v
    return v, h, u, s, cp, cv, w

def Region3_from_TP(T, P):
    rho_lo = 50.0
    rho_hi = 1050.0
    for _ in range(100):
        rho_mid = 0.5 * (rho_lo + rho_hi)
        if rho_hi - rho_lo < 1e-12 * rho_mid:
            break
        P_mid = _region3_pressure(rho_mid, T)
        if P_mid < P:
            rho_lo = rho_mid
        else:
            rho_hi = rho_mid
    rho = 0.5 * (rho_lo + rho_hi)
    return Region3_rhoT(rho, T)


# ===== Region 5 (pure Python) =====
R5_J0 = [0, 1, -3, -2, -1, 2]
R5_n0 = [
   -0.13179983674201e+02,  0.68540841634434e+01, -0.24805148933466e-01,
    0.36901534980333e+00, -0.31161318213925e+01, -0.32961626538917e+00]
R5_Ir = [1, 1, 1, 2, 2, 3]
R5_Jr = [1, 2, 3, 3, 9, 7]
R5_nr = [
    0.15736404855259e-02,  0.90153761673944e-03, -0.50270077677648e-02,
    0.22440037409485e-05, -0.41163275453471e-05,  0.37919454822955e-07]

def Region5(T, P):
    tau = 1000.0 / T
    pi = P
    go = math.log(pi)
    gop = 1.0 / pi
    gopp = -1.0 / pi**2
    got = 0.0
    gott = 0.0
    for k in range(6):
        J0 = R5_J0[k]
        n0 = R5_n0[k]
        go += n0 * tau**J0
        if J0 != 0:
            got += n0 * J0 * tau**(J0 - 1)
            if J0 != 1:
                gott += n0 * J0 * (J0 - 1) * tau**(J0 - 2)
    gr = 0.0
    grp = 0.0
    grpp = 0.0
    grt = 0.0
    grtt = 0.0
    grpt = 0.0
    for k in range(6):
        Ik = R5_Ir[k]
        Jk = R5_Jr[k]
        nk = R5_nr[k]
        pi_Ik = pi**Ik
        tau_Jk = tau**Jk
        gr += nk * pi_Ik * tau_Jk
        if Ik != 0:
            grp += nk * Ik * pi**(Ik - 1) * tau_Jk
            if Ik >= 2:
                grpp += nk * Ik * (Ik - 1) * pi**(Ik - 2) * tau_Jk
        if Jk != 0:
            grt += nk * Jk * pi_Ik * tau**(Jk - 1)
            if Jk != 1:
                grtt += nk * Jk * (Jk - 1) * pi_Ik * tau**(Jk - 2)
        if Ik != 0 and Jk != 0:
            grpt += nk * Ik * Jk * pi**(Ik - 1) * tau**(Jk - 1)
    v = pi * (gop + grp) * R * T / P / 1000
    h = tau * (got + grt) * R * T
    s = R * (tau * (got + grt) - (go + gr))
    cp = -R * tau**2 * (gott + grtt)
    cv = R * (-tau**2 * (gott + grtt) - (1 + pi * grp - tau * pi * grpt)**2 / (1 - pi**2 * grpp))
    w = (R * T * 1000 * (1 + 2 * pi * grp + pi**2 * grp**2) /
         (1 - pi**2 * grpp + (1 + pi * grp - tau * pi * grpt)**2 / tau**2 / (gott + grtt)))**0.5
    u = h - P * 1000 * v
    return v, h, u, s, cp, cv, w


# ===== Backward equations =====
# Region 1 T(P,h) - Table 6
B1ph_I = [0,0,0,0,0,0,1,1,1,1,1,1,1,2,2,3,3,4,5,6]
B1ph_J = [0,1,2,6,22,32,0,1,2,3,4,10,32,10,32,10,32,32,32,32]
B1ph_n = [
   -0.23872489924521e+03,  0.40421188637945e+03,  0.11349746881718e+03,
   -0.58457616048039e+01, -0.15285482413140e-03, -0.10866707695377e-05,
   -0.13391744872602e+02,  0.43211039183559e+02, -0.54010067170506e+02,
    0.30535892203916e+02, -0.65964749423638e+01,  0.93965400878363e-02,
    0.11573647505340e-06, -0.25858641282073e-04, -0.40644363084799e-08,
    0.66456186191635e-07,  0.80670734103027e-10, -0.93477771213947e-12,
    0.58265442020601e-14, -0.15020185953503e-16]

# Region 1 T(P,s) - Table 8
B1ps_I = [0,0,0,0,0,0,1,1,1,1,1,1,2,2,2,2,2,3,3,4]
B1ps_J = [0,1,2,3,11,31,0,1,2,3,12,31,0,1,2,9,31,10,32,32]
B1ps_n = [
    0.17478268058307e+03,  0.34806930892873e+02,  0.65292584978455e+01,
    0.33039981775489e+00, -0.19281382923196e-06, -0.24909197244573e-22,
   -0.26107636489332e+00,  0.22592965981586e+00, -0.64256463395226e-01,
    0.78876289270526e-02,  0.35672110607366e-09,  0.17332496994895e-23,
    0.56608900654837e-03, -0.32635483139717e-03,  0.44778286690632e-04,
   -0.51322156908507e-09, -0.42522657042207e-25,  0.26400441360689e-12,
    0.78124600459723e-28, -0.30732199903668e-30]

# Region 2a T(P,h) - Table 20
B2aph_I = [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,3,3,4,4,4,5,5,5,6,6,7]
B2aph_J = [0,1,2,3,7,20,0,1,2,3,7,9,11,18,44,0,2,7,36,38,40,42,44,24,44,12,32,44,32,36,42,34,44,28]
B2aph_n = [
    0.10898952318288e+04,  0.84951654495535e+03, -0.10781748091826e+03,
    0.33153654801263e+02, -0.74232016790248e+01,  0.11765048724356e+02,
    0.18445749355790e+01, -0.41792700549624e+01,  0.62478196935812e+01,
   -0.17344563108114e+02, -0.20058176862096e+03,  0.27196065473796e+03,
   -0.45511318285818e+03,  0.30919688604755e+04,  0.25226640357872e+06,
   -0.61707422868339e-02, -0.31078046629583e+00,  0.11670873077107e+02,
    0.12812798404046e+09, -0.98554909623276e+09,  0.28224546973002e+10,
   -0.35948971410703e+10,  0.17227349913197e+10, -0.13551334240775e+05,
    0.12848734664650e+08,  0.13865724283226e+01,  0.23598832556514e+06,
   -0.13105236545054e+08,  0.73999835474766e+04, -0.55196697030060e+06,
    0.37154085996233e+07,  0.19127729239660e+05, -0.41535164835634e+06,
   -0.62459855192507e+02]

# Region 2b T(P,h) - Table 21
B2bph_I = [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,4,4,5,5,5,6,7,7,9,9]
B2bph_J = [0,1,2,12,18,24,28,40,0,2,6,12,18,24,28,40,2,8,18,40,1,2,12,24,2,12,18,24,28,40,18,24,40,28,2,28,1,40]
B2bph_n = [
    0.14895041079516e+04,  0.74307798314034e+03, -0.97708318797837e+02,
    0.24742464705674e+01, -0.63281320016026e+00,  0.11385952129658e+01,
   -0.47811863648625e+00,  0.85208123431544e-02,  0.93747147377932e+00,
    0.33593118604916e+01,  0.33809355601454e+01,  0.16844539671904e+00,
    0.73875745236695e+00, -0.47128737436186e+00,  0.15020273139707e+00,
   -0.21764114219750e-02, -0.21810755324761e-01, -0.10829784403677e+00,
   -0.46333324635812e-01,  0.71280351959551e-04,  0.11032831789999e-03,
    0.18955248387902e-03,  0.30891541160537e-02,  0.13555504554949e-02,
    0.28640237477456e-06, -0.10779857357512e-04, -0.76462712454814e-04,
    0.14052392818316e-04, -0.31083814331434e-04, -0.10302738212103e-05,
    0.28217281635040e-06,  0.12704902271945e-05,  0.73803353468292e-07,
   -0.11030139238909e-07, -0.81456365207833e-13, -0.25180545682962e-10,
   -0.17565233969407e-17,  0.86934156344163e-14]

# Region 2c T(P,h) - Table 22
B2cph_I = [-7,-7,-6,-6,-5,-5,-2,-2,-1,-1,0,0,1,1,2,6,6,6,6,6,6,6,6]
B2cph_J = [0,4,0,2,0,2,0,1,0,2,0,1,4,8,4,0,1,4,10,12,16,20,22]
B2cph_n = [
   -0.32368398555242e+13,  0.73263350902181e+13,  0.35825089945447e+12,
   -0.58340131851590e+12, -0.10783068217470e+11,  0.20825544563171e+11,
    0.61074783564516e+06,  0.85977722535580e+06, -0.25745723604170e+05,
    0.31081088422714e+05,  0.12082315865936e+04,  0.48219755109255e+03,
    0.37966001272486e+01, -0.10842984880077e+02, -0.45364172676660e-01,
    0.14559115658698e-12,  0.11261597407230e-11, -0.17804982240686e-10,
    0.12324579690832e-06, -0.11606921130984e-05,  0.27846367088554e-04,
   -0.59270038474176e-03,  0.12918582991878e-02]

# Region 2a T(P,s) - Table 25
B2aps_I = [-1.5,-1.5,-1.5,-1.5,-1.5,-1.5,-1.25,-1.25,-1.25,-1.0,-1.0,-1.0,
           -1.0,-1.0,-1.0,-0.75,-0.75,-0.5,-0.5,-0.5,-0.5,-0.25,-0.25,
           -0.25,-0.25,0.25,0.25,0.25,0.25,0.5,0.5,0.5,0.5,0.5,0.5,0.5,
           0.75,0.75,0.75,0.75,1.0,1.0,1.25,1.25,1.5,1.5]
B2aps_J = [-24,-23,-19,-13,-11,-10,-19,-15,-6,-26,-21,-17,-16,-9,-8,
           -15,-14,-26,-13,-9,-7,-27,-25,-11,-6,1,4,8,11,0,1,5,6,
           10,14,16,0,4,9,17,7,18,3,15,5,18]
B2aps_n = [
   -0.39235983861984e+06,  0.51526573827270e+06,  0.40482443161048e+05,
   -0.32193790923902e+03,  0.96961424218694e+02, -0.22867846371773e+02,
   -0.44942914124357e+06, -0.50118336020166e+04,  0.35684463560015e+00,
    0.44235335848190e+05, -0.13673388811708e+05,  0.42163260207864e+06,
    0.22516925837475e+05,  0.47442144865646e+03, -0.14931130797647e+03,
   -0.19781126320452e+06, -0.23554399470760e+05, -0.19070616302076e+05,
    0.55375669883164e+05,  0.38293691437363e+04, -0.60391860580567e+03,
    0.19363102620331e+04,  0.42660643698610e+04, -0.59780638872718e+04,
   -0.70401463926862e+03,  0.33836784107553e+03,  0.20862786635187e+02,
    0.33834172656196e-01, -0.43124428414893e-04,  0.16653791356412e+03,
   -0.13986292055898e+03, -0.78849547999872e+00,  0.72132411753872e-01,
   -0.59754839398283e-02, -0.12141358953904e-04,  0.23227096733871e-06,
   -0.10538463566194e+02,  0.20718925496502e+01, -0.72193155260427e-01,
    0.20749887081120e-06, -0.18340657911379e-01,  0.29036272348696e-06,
    0.21037527893619e+00,  0.25681239729999e-03, -0.12799002933781e-01,
   -0.82198102652018e-05]

# Region 2b T(P,s) - Table 26
B2bps_I = [-6,-6,-5,-5,-4,-4,-4,-3,-3,-3,-3,-2,-2,-2,-2,-1,-1,-1,
           -1,-1,0,0,0,0,0,0,0,1,1,1,1,1,1,2,2,2,3,3,3,4,4,5,5,5]
B2bps_J = [0,11,0,11,0,1,11,0,1,11,12,0,1,6,10,0,1,5,8,9,0,1,2,
           4,5,6,9,0,1,2,3,7,8,0,1,5,0,1,3,0,1,0,1,2]
B2bps_n = [
    0.31687665083497e+06,  0.20864175881858e+02, -0.39859399803599e+06,
   -0.21816058518877e+02,  0.22369785194242e+06, -0.27841703445817e+04,
    0.99207436071480e+01, -0.75197512299157e+05,  0.29708605951158e+04,
   -0.34406878548526e+01,  0.38815564249115e+00,  0.17511295085750e+05,
   -0.14237112854449e+04,  0.10943803364167e+01,  0.89971619308495e+00,
   -0.33759740098958e+04,  0.47162885818355e+03, -0.19188241993679e+01,
    0.41078580492196e+00, -0.33465378172097e+00,  0.13870034777505e+04,
   -0.40663326195838e+03,  0.41727347159610e+02,  0.21932549434532e+01,
   -0.10320050009077e+01,  0.35882943516703e+00,  0.52511453726066e-02,
    0.12838916450705e+02, -0.28642437219381e+01,  0.56912683664855e+00,
   -0.99962954584931e-01, -0.32632037778459e-02,  0.23320922576723e-03,
   -0.15334809857450e+00,  0.29072288239902e-01,  0.37534702741167e-03,
    0.17296691702411e-02, -0.38556050844504e-03, -0.35017712292608e-04,
   -0.14566393631492e-04,  0.56420857267269e-05,  0.41286150074605e-07,
   -0.20684671118824e-07,  0.16409393674725e-08]

# Region 2c T(P,s) - Table 27
B2cps_I = [-2,-2,-1,0,0,0,0,1,1,1,1,2,2,2,3,3,3,4,4,4,5,5,5,6,6,7,7,7,7,7]
B2cps_J = [0,1,0,0,1,2,3,0,1,3,4,0,1,2,0,1,5,0,1,4,0,1,2,0,1,0,1,3,4,5]
B2cps_n = [
    0.90968501005365e+03,  0.24045667088420e+04, -0.59162326387130e+03,
    0.54145404128074e+03, -0.27098308411192e+03,  0.97976525097926e+03,
   -0.46966772959435e+03,  0.14399274604723e+02, -0.19104204230429e+02,
    0.53299167111971e+01, -0.21252975375934e+02, -0.31147334413760e+00,
    0.60334840894623e+00, -0.42764839702509e-01,  0.58185597255259e-02,
   -0.14597008284753e-01,  0.56631175631027e-02, -0.76155864584577e-04,
    0.22440342919332e-03, -0.12561095013413e-04,  0.63323132660934e-06,
   -0.20541989675375e-05,  0.36405370390082e-07, -0.29759897789215e-08,
    0.10136618529763e-07,  0.59925719692351e-11, -0.20677870105164e-10,
   -0.20874278181886e-10,  0.10162166825089e-09, -0.16429828281347e-09]


def Backward1_T_Ph(P, h):
    pi = P
    eta = h / 2500.0
    T = 0.0
    for k in range(20):
        T += B1ph_n[k] * pi**B1ph_I[k] * (eta + 1)**B1ph_J[k]
    return T

def Backward1_T_Ps(P, s):
    pi = P
    sigma = s
    T = 0.0
    for k in range(20):
        T += B1ps_n[k] * pi**B1ps_I[k] * (sigma + 2)**B1ps_J[k]
    return T

def Backward2a_T_Ph(P, h):
    pi = P
    eta = h / 2000.0
    T = 0.0
    for k in range(34):
        T += B2aph_n[k] * pi**B2aph_I[k] * (eta - 2.1)**B2aph_J[k]
    return T

def Backward2b_T_Ph(P, h):
    pi = P
    eta = h / 2000.0
    T = 0.0
    for k in range(38):
        T += B2bph_n[k] * (pi - 2)**B2bph_I[k] * (eta - 2.6)**B2bph_J[k]
    return T

def Backward2c_T_Ph(P, h):
    pi = P
    eta = h / 2000.0
    T = 0.0
    for k in range(23):
        T += B2cph_n[k] * (pi + 25)**B2cph_I[k] * (eta - 1.8)**B2cph_J[k]
    return T

def Backward2_T_Ph(P, h):
    if P <= 4:
        return Backward2a_T_Ph(P, h)
    elif P <= 6.546699678:
        return Backward2b_T_Ph(P, h)
    else:
        hf = _hbc_P(P)
        if h >= hf:
            return Backward2b_T_Ph(P, h)
        else:
            return Backward2c_T_Ph(P, h)

def Backward2a_T_Ps(P, s):
    pi = P
    sigma = s / 2.0
    T = 0.0
    for k in range(46):
        T += B2aps_n[k] * pi**B2aps_I[k] * (sigma - 2)**B2aps_J[k]
    return T

def Backward2b_T_Ps(P, s):
    pi = P
    sigma = s / 0.7853
    T = 0.0
    for k in range(44):
        T += B2bps_n[k] * pi**B2bps_I[k] * (10 - sigma)**B2bps_J[k]
    return T

def Backward2c_T_Ps(P, s):
    pi = P
    sigma = s / 2.9251
    T = 0.0
    for k in range(30):
        T += B2cps_n[k] * pi**B2cps_I[k] * (2 - sigma)**B2cps_J[k]
    return T

def Backward2_T_Ps(P, s):
    if P <= 4:
        return Backward2a_T_Ps(P, s)
    elif s >= 5.85:
        return Backward2b_T_Ps(P, s)
    else:
        return Backward2c_T_Ps(P, s)


# ===== Property dispatch =====
def props_TP(T, P):
    reg = region_TP(T, P)
    if reg == 1:
        return Region1(T, P)
    elif reg == 2:
        return Region2(T, P)
    elif reg == 3:
        return Region3_from_TP(T, P)
    elif reg == 5:
        return Region5(T, P)
    else:
        raise ValueError("T={}, P={} outside IF97 range".format(T, P))


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: if97 <mode> <args...>", file=sys.stderr)
        sys.exit(1)

    mode = args[0]

    if mode == "region":
        T = float(args[1])
        P = float(args[2])
        print(region_TP(T, P))

    elif mode == "props":
        T = float(args[1])
        P = float(args[2])
        v, h, u, s, cp, cv, w = props_TP(T, P)
        print("{:.12g} {:.12g} {:.12g} {:.12g} {:.12g} {:.12g} {:.12g}".format(
            v, h, u, s, cp, cv, w))

    elif mode == "satT":
        T = float(args[1])
        print("{:.12g}".format(PSat_T(T)))

    elif mode == "satP":
        P = float(args[1])
        print("{:.12g}".format(TSat_P(P)))

    elif mode == "backward_ph":
        P = float(args[1])
        h = float(args[2])
        if P <= Pc:
            Tsat = TSat_P(P)
            h1_sat = Region1(Tsat, P)[1]
            if h <= h1_sat:
                T = Backward1_T_Ph(P, h)
            else:
                T = Backward2_T_Ph(P, h)
        else:
            h_623 = Region1(623.15, P)[1]
            if h <= h_623:
                T = Backward1_T_Ph(P, h)
            else:
                T = Backward2_T_Ph(P, h)
        print("{:.12g}".format(T))

    elif mode == "backward_ps":
        P = float(args[1])
        s = float(args[2])
        if P <= Pc:
            Tsat = TSat_P(P)
            s1_sat = Region1(Tsat, P)[3]
            if s <= s1_sat:
                T = Backward1_T_Ps(P, s)
            else:
                T = Backward2_T_Ps(P, s)
        else:
            s_623 = Region1(623.15, P)[3]
            if s <= s_623:
                T = Backward1_T_Ps(P, s)
            else:
                T = Backward2_T_Ps(P, s)
        print("{:.12g}".format(T))

    else:
        print("Unknown mode: {}".format(mode), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
