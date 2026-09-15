"""
WCV_TAUMOD Conflict Detection — Implementation from PVS Formal Specifications

This module implements the Well-Clear Volume with Tau-Modified time variable
(WCV_TAUMOD) conflict detection algorithm as specified in the PVS formal
specifications from the NASA DAIDALUS project.


References:
    - WCV.pvs: Generic 3D Well-Clear Volume framework
    - WCV_taumod.pvs: WCV instantiated with tau-modified time variable
    - horizontal_WCV_taumod.pvs: Horizontal interval computation
    - vertical_WCV.pvs: Vertical interval computation
    - DWC.pvs: Standard DAA Well-Clear volume parameters

Units:
    - Horizontal distance/position: nautical miles (nmi)
    - Horizontal velocity: nmi/s
    - Vertical distance/position: feet (ft)
    - Vertical velocity: ft/s
    - Time: seconds (s)
"""

import math


def _sq(x):
    """Square of a scalar: sq(x) = x^2"""
    return x * x


def _sqv2(v):
    """Squared norm of a 2D vector: sqv(v) = v[0]^2 + v[1]^2"""
    return v[0] ** 2 + v[1] ** 2


def _dot2(a, b):
    """Dot product of 2D vectors: a*b = a[0]*b[0] + a[1]*b[1]"""
    return a[0] * b[0] + a[1] * b[1]


def horizontal_wcv_taumod_interval(T, s, v, TAUMOD, DTHR):
    """
    Compute the horizontal WCV_TAUMOD entry/exit interval.

    From horizontal_WCV_taumod.pvs:

    horizontal_WCV_taumod_interval(T, s, v): EntryExit[0,T] =
        LET a = sqv(v),
            b = 2*(s*v) + TAUMOD*sqv(v),
            c = sqv(s) + TAUMOD*(s*v) - sq(DTHR) IN
        IF a = 0 AND sqv(s) <= sq(DTHR) THEN WholeInterval[0,T]
        ELSIF sqv(s) <= sq(DTHR) THEN (#entry:=0, exit:=min(T,Theta_D[DTHR](s,v,1))#)
        ELSIF s*v >= 0 OR discr(a,b,c) < 0 THEN EmptyInterval[0,T]
        ELSIF Delta[DTHR](s,v) >= 0 AND root(a,b,c,-1) <= T THEN
            (#entry:=max(0,root(a,b,c,-1)), exit:=min(T,Theta_D[DTHR](s,v,1))#)
        ELSE EmptyInterval[0,T]

    Args:
        T: lookahead time (positive real), seconds
        s: relative horizontal position (sx, sy) in nmi, ownship - intruder
        v: relative horizontal velocity (vx, vy) in nmi/s
        TAUMOD: modified tau time threshold, seconds
        DTHR: horizontal distance threshold, nmi

    Returns:
        (entry, exit) tuple in seconds. Empty interval: entry > exit.
    """
    ss = _sqv2(s)
    vv = _sqv2(v)
    sv = _dot2(s, v)
    d2 = _sq(DTHR)

    a = vv
    b = 2.0 * sv + TAUMOD * vv
    c = ss + TAUMOD * sv - d2

    # Case 1: a = 0 (zero relative velocity)
    if a < 1e-30:
        if ss <= d2:
            return (0.0, T)  # WholeInterval
        else:
            return (T, 0.0)  # EmptyInterval

    # Case 2: Already within DTHR
    if ss <= d2:
        # entry = 0, exit = min(T, Theta_D[DTHR](s,v,1))
        # Theta_D[D](s,v,eps) = (-(s*v) + eps*sqrt(Delta[D](s,v))) / sqv(v)
        # Delta[D](s,v) = (s*v)^2 - sqv(v)*(sqv(s) - sq(D))
        delta = sv ** 2 - vv * (ss - d2)
        if delta < 0:
            # Shouldn't happen when ss <= d2, but handle gracefully
            return (T, 0.0)
        theta_d_exit = (-sv + math.sqrt(delta)) / vv
        return (0.0, min(T, theta_d_exit))

    # Case 3: Outside DTHR, diverging or no discriminant
    if sv >= 0:
        return (T, 0.0)  # EmptyInterval (diverging)

    # discr(a,b,c) = b^2 - 4*a*c
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return (T, 0.0)  # EmptyInterval

    # Case 4: Check Delta and root
    # Delta[DTHR](s,v) = (s*v)^2 - sqv(v)*(sqv(s) - sq(DTHR))
    delta = sv ** 2 - vv * (ss - d2)
    if delta < 0:
        return (T, 0.0)  # EmptyInterval

    # root(a,b,c,-1) = (-b - sqrt(disc)) / (2*a)
    root_neg = (-b - math.sqrt(disc)) / (2.0 * a)
    if root_neg > T:
        return (T, 0.0)  # EmptyInterval

    # Theta_D[DTHR](s,v,1) = (-(s*v) + sqrt(delta)) / sqv(v)
    theta_d_exit = (-sv + math.sqrt(delta)) / vv

    entry = max(0.0, root_neg)
    exit_time = min(T, theta_d_exit)

    return (entry, exit_time)


def _theta_H(H, sz, vz, eps):
    """
    Compute altitude crossing time for the vertical WCV.

    From ACCoRD@vertical theory, Theta_H computes when |sz + t*vz| crosses
    the altitude boundary H. eps=-1 gives the entry (earlier) crossing,
    eps=+1 gives the exit (later) crossing.

    The formula accounts for the sign of vz:
    - vz > 0 (closing from below): entry at lower boundary, exit at upper
    - vz < 0 (closing from above): entry at upper boundary, exit at lower

    Args:
        H: altitude threshold (positive)
        sz: relative altitude (ft)
        vz: relative vertical speed (ft/s), must be non-zero
        eps: -1 for entry, +1 for exit

    Returns:
        Time of crossing in seconds
    """
    if eps * vz > 0:
        return (H - sz) / vz
    else:
        return (-H - sz) / vz


def vertical_wcv_interval(B, T, sz, vz, TCOA, ZTHR):
    """
    Compute the vertical WCV entry/exit interval.

    From vertical_WCV.pvs:

    vertical_WCV_interval(B, T, sz, vz): EntryExit[B,T] =
        IF vz = 0 AND abs(sz) <= ZTHR THEN WholeInterval[B,T]
        ELSIF vz = 0 THEN EmptyInterval[B,T]
        ELSE
            LET (centry,cexit) = coalt_entry_exit(sz,vz) IN
            IF T < centry OR cexit < B THEN EmptyInterval[B,T]
            ELSE (#entry:=max(B,centry), exit:=min(T,cexit)#)
        ENDIF

    coalt_entry_exit(sz, vz) =
        LET act_H = max(ZTHR, abs(vz)*TCOA)
        IN (Theta_H[act_H](sz,vz,-1), Theta_H[ZTHR](sz,vz,1))

    Args:
        B: begin of lookahead window (seconds)
        T: end of lookahead window (seconds)
        sz: relative altitude (ft), ownship - intruder
        vz: relative vertical speed (ft/s)
        TCOA: time-to-coaltitude threshold (seconds)
        ZTHR: vertical altitude threshold (ft)

    Returns:
        (entry, exit) tuple in seconds. Empty interval: entry > exit.
    """
    if abs(vz) < 1e-15:
        # Zero vertical speed
        if abs(sz) <= ZTHR:
            return (B, T)  # WholeInterval
        else:
            return (T, B)  # EmptyInterval

    # Compute coalt_entry_exit
    act_H = max(ZTHR, abs(vz) * TCOA)
    centry = _theta_H(act_H, sz, vz, -1)
    cexit = _theta_H(ZTHR, sz, vz, 1)

    if T < centry or cexit < B:
        return (T, B)  # EmptyInterval

    return (max(B, centry), min(T, cexit))


def _horizontal_wcv_taumod_check(s, v, TAUMOD, DTHR):
    """
    Instantaneous horizontal WCV_TAUMOD check.

    horizontal_WCV_taumod(s,v) IFF
        sqv(s) <= sq(DTHR) OR
        (s*v < 0 AND sqv(s+tcpa(s,v)*v) <= sq(DTHR) AND tau_mod(s,v) <= TAUMOD)

    Where tau_mod(s,v) = (sq(DTHR) - sqv(s)) / (s*v) when s*v < 0
    """
    ss = _sqv2(s)
    d2 = _sq(DTHR)
    if ss <= d2:
        return True
    sv = _dot2(s, v)
    if sv >= 0:
        return False
    vv = _sqv2(v)
    if vv < 1e-30:
        return False
    # tcpa = -sv/vv
    tc = -sv / vv
    sc = (s[0] + tc * v[0], s[1] + tc * v[1])
    if _sqv2(sc) > d2:
        return False
    # tau_mod = (sq(DTHR) - sqv(s)) / (s*v)
    tau_m = (d2 - ss) / sv
    return 0 <= tau_m <= TAUMOD


def wcv_taumod_interval(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR):
    """
    Compute the 3D WCV_TAUMOD entry/exit interval.

    From WCV.pvs:

    WCV_interval(tvar, hi)(B, T, s, v): EntryExit[B,T] =
        LET ventryexit = vertical_WCV_interval(B, T, s`z, v`z),
            (ventry, vexit) = (ventryexit`entry, ventryexit`exit)
        IN IF ventry > vexit THEN EmptyInterval
           ELSIF ventry = vexit AND horizontal_WCV(tvar)(vect2(s)+ventry*vect2(v), vect2(v))
             THEN (#entry:=ventry, exit:=ventry#)
           ELSIF ventry = vexit THEN EmptyInterval
           ELSE
             LET hni = hi(vexit-ventry, vect2(s)+ventry*vect2(v), vect2(v))
             IN (#entry:= hni`entry+ventry, exit:= hni`exit+ventry#)
           ENDIF

    Args:
        B: begin of lookahead (seconds)
        T: end of lookahead (seconds)
        s3: relative 3D position (sx_nmi, sy_nmi, sz_ft)
        v3: relative 3D velocity (vx_nmi_s, vy_nmi_s, vz_ft_s)
        TAUMOD: modified tau threshold (seconds)
        TCOA: time-to-coaltitude threshold (seconds)
        DTHR: horizontal distance threshold (nmi)
        ZTHR: vertical altitude threshold (ft)

    Returns:
        (entry, exit) tuple in seconds. Empty interval: entry > exit.
    """
    s2 = (s3[0], s3[1])
    v2 = (v3[0], v3[1])
    sz = s3[2]
    vz = v3[2]

    # Step 1: Compute vertical interval
    ve, vx = vertical_wcv_interval(B, T, sz, vz, TCOA, ZTHR)

    # Empty vertical interval
    if ve > vx:
        return (T, B)

    # Single-point vertical interval
    if abs(ve - vx) < 1e-15:
        ss = (s2[0] + ve * v2[0], s2[1] + ve * v2[1])
        if _horizontal_wcv_taumod_check(ss, v2, TAUMOD, DTHR):
            return (ve, ve)
        return (T, B)

    # Step 2: Evaluate horizontal within vertical window
    # Shift horizontal state to start of vertical window
    sh = (s2[0] + ve * v2[0], s2[1] + ve * v2[1])
    he, hx = horizontal_wcv_taumod_interval(vx - ve, sh, v2, TAUMOD, DTHR)

    if he > hx:
        return (T, B)

    # Shift back to original time frame
    return (he + ve, hx + ve)


def wcv_taumod_detection(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR):
    """
    Detect whether a WCV_TAUMOD conflict exists within [B, T].

    From WCV.pvs:

    WCV_detection(tvar, hi)(B, T, s, v): bool =
        IF B = T THEN WCV(tvar)(s+B*v, v)
        ELSIF B > T THEN FALSE
        ELSE LET nwcint = WCV_interval(tvar,hi)(B,T,s,v)
             IN nwcint`entry <= nwcint`exit
        ENDIF

    Args:
        B: begin of lookahead (seconds)
        T: end of lookahead (seconds)
        s3: relative 3D position (sx_nmi, sy_nmi, sz_ft)
        v3: relative 3D velocity (vx_nmi_s, vy_nmi_s, vz_ft_s)
        TAUMOD: modified tau threshold (seconds)
        TCOA: time-to-coaltitude threshold (seconds)
        DTHR: horizontal distance threshold (nmi)
        ZTHR: vertical altitude threshold (ft)

    Returns:
        True if conflict detected, False otherwise.
    """
    if abs(B - T) < 1e-15:
        # B = T edge case: check instantaneous WCV
        return False
    if B > T:
        return False
    e, x = wcv_taumod_interval(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR)
    return e <= x
