#!/usr/bin/env python3
"""
Propagator-matrix method for viscoelastic Love numbers and relaxation spectrum.

Reads Earth model from TABOO Make_Model format configuration, resolves
physical parameters, and computes loading Love numbers.

"""

import json
import os
import numpy as np

G_NEWTON = 6.6732e-11
PI = np.pi
KYR_IN_SECONDS = 1000.0 * 365.25 * 24.0 * 3600.0

# Model profiles extracted from TABOO Fortran source (subroutine SPEC)
# Key: (NV, CODE) -> {radii_m, densities_kgm3, rigidities_Pa}
MODEL_PROFILES = {
    (2, 2): {
        # Yuen Sabadini Boschi [1982], LT=100 km
        'radii_m': [3480000.0, 5701000.0, 6271000.0, 6371000.0],
        'densities_kgm3': [10927.0, 4919.0, 4430.0, 2689.0],
        'rigidities_Pa': [0.0, 2.17e11, 8.37e10, 2.82e10],
    },
}


def parse_taboo_config(path):
    """Parse TABOO Make_Model format configuration file."""
    with open(path) as f:
        lines = f.readlines()

    lmin = lmax = None
    nv = code = None
    lt = 0.0
    viscosities = []

    i = 0
    while i < len(lines):
        stripped = lines[i].split('!')[0].strip()

        if stripped == 'Harmonic_Degrees':
            i += 1
            while i < len(lines):
                vals = lines[i].split('!')[0].split()
                if len(vals) >= 2:
                    lmin, lmax = int(vals[0]), int(vals[1])
                    break
                i += 1

        elif stripped == 'Make_Model':
            i += 1
            params = []
            while i < len(lines) and len(params) < 4:
                val = lines[i].split('!')[0].strip()
                if val:
                    params.append(val)
                i += 1
            nv = int(params[0])
            code = int(params[1])
            lt = float(params[2])
            # skip ILM param (params[3])
            # read viscosities (nv values, bottom to top)
            viscosities = []
            while i < len(lines) and len(viscosities) < nv:
                val = lines[i].split('!')[0].strip()
                if val:
                    viscosities.append(float(val))
                i += 1
            break

        i += 1

    return {
        'nv': nv, 'code': code, 'lt': lt,
        'viscosities': viscosities,
        'lmin': lmin, 'lmax': lmax,
    }


def build_model(config):
    """Resolve model-type identifiers to physical parameters."""
    key = (config['nv'], config['code'])
    if key not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile NV={config['nv']}, CODE={config['code']}")

    profile = MODEL_PROFILES[key]
    nv = config['nv']
    # Viscosity array: [core=0, ...VE layers bottom-to-top..., lithosphere=0]
    vis = [0.0] + [v * 1e21 for v in config['viscosities']] + [0.0]

    return {
        'nv': nv,
        'radii_m': profile['radii_m'],
        'densities_kgm3': profile['densities_kgm3'],
        'rigidities_Pa': profile['rigidities_Pa'],
        'viscosities_Pas': vis,
        'lmin': config['lmin'],
        'lmax': config['lmax'],
        'loading': True,
    }


def diretta(n, r, rho, za, gra):
    """Direct fundamental matrix Y(r)."""
    a = np.zeros((6, 6))
    b = np.zeros((6, 6))
    rn = float(n)
    a1 = rn / (2.0 * (2.0 * rn + 3.0))
    a2 = 1.0
    a3 = (rn + 1.0) / (2.0 * (2.0 * rn - 1.0))
    a4 = 1.0
    b1 = (rn + 3.0) / (2.0 * (2.0 * rn + 3.0) * (rn + 1.0))
    b2 = 1.0 / rn
    b3 = (-rn + 2.0) / (2.0 * rn * (2.0 * rn - 1.0))
    b4 = -1.0 / (rn + 1.0)
    c1 = (rn * rn - rn - 3.0) / (2.0 * rn + 3.0)
    c2 = 2.0 * (rn - 1.0)
    c3 = (-rn * rn - 3.0 * rn + 1.0) / (2.0 * rn - 1.0)
    c4 = -2.0 * (rn + 2.0)
    d1 = rn * (rn + 2.0) / ((2.0 * rn + 3.0) * (rn + 1.0))
    d2 = 2.0 * (rn - 1.0) / rn
    d3 = (rn * rn - 1.0) / (rn * (2.0 * rn - 1.0))
    d4 = 2.0 * (rn + 2.0) / (rn + 1.0)
    a[0, 0] = a1 * r ** (n + 1); a[0, 1] = a2 * r ** (n - 1)
    a[0, 3] = a3 * r ** (-n);    a[0, 4] = a4 * r ** (-n - 2)
    a[1, 0] = b1 * r ** (n + 1); a[1, 1] = b2 * r ** (n - 1)
    a[1, 3] = b3 * r ** (-n);    a[1, 4] = b4 * r ** (-n - 2)
    a[2, 0] = a[0, 0] * rho * gra; a[2, 1] = a[0, 1] * rho * gra
    a[2, 2] = -rho * r ** n; a[2, 3] = a[0, 3] * rho * gra
    a[2, 4] = a[0, 4] * rho * gra; a[2, 5] = -rho * r ** (-n - 1)
    a[4, 2] = a[2, 2] / rho; a[4, 5] = a[2, 5] / rho
    a[5, 0] = 3.0 * za * a[0, 0]; a[5, 1] = 3.0 * za * a[0, 1]
    a[5, 2] = -(2.0 * rn + 1.0) * r ** (n - 1)
    a[5, 3] = 3.0 * za * a[0, 3]; a[5, 4] = 3.0 * za * a[0, 4]
    b[2, 0] = c1 * r ** n; b[2, 1] = c2 * r ** (n - 2)
    b[2, 3] = c3 * r ** (-n - 1); b[2, 4] = c4 * r ** (-n - 3)
    b[3, 0] = d1 * r ** n; b[3, 1] = d2 * r ** (n - 2)
    b[3, 3] = d3 * r ** (-n - 1); b[3, 4] = d4 * r ** (-n - 3)
    return a, b


def inversa(n, r, rho, za, gra):
    """Inverse fundamental matrix Y^{-1}(r)."""
    a = np.zeros((6, 6))
    b = np.zeros((6, 6))
    rn = float(n)
    h1 = rn + 1.0; h2 = 1.0 + 2.0 * rn; h3 = 2.0 * rn - 1.0
    h4 = 3.0 + 2.0 * rn; h5 = rn - 1.0
    v = np.zeros(25)
    v[1] = h1/h2; v[2] = -2.0*h1*(rn+2.0)/h2
    v[3] = rn*h1/2.0/h3/h2; v[4] = -(rn**2+3.0*rn-1.0)*rn/h2/h3
    v[5] = rn/h2; v[6] = 2.0*rn*h5/h2
    v[7] = rn*h1/2.0/h2/h4; v[8] = h1*(rn**2-rn-3.0)/h2/h4
    v[9] = -2.0*rn*h1*(2.0+rn)/h2; v[10] = -h5*rn*h1*h1/h3/h2
    v[11] = -2.0*h5*rn*h1/h2; v[12] = -rn**2*h1*(2.0+rn)/h2/h4
    v[13]=-v[1]; v[14]=-v[3]; v[15]=-v[5]; v[16]=-v[7]
    v[17] = -rn*h1/h2; v[18] = (2.0-rn)*h1*rn/2.0/h3/h2
    v[19] = rn*h1/h2; v[20] = rn*h1*(3.0+rn)/2.0/h2/h4
    v[21]=-v[1]; v[22]=-v[3]; v[23]=-v[5]; v[24]=-v[7]
    a[0,0]=r**(-n-1)*v[2]; a[1,0]=-r**(-n+1)*v[4]
    a[2,0]=3.0*za*r**(-n+1)/(2.0*rn+1.0)
    a[3,0]=r**n*v[6]; a[4,0]=-r**(n+2)*v[8]
    a[5,0]=-3.0*za*r**(n+2)/(2.0*rn+1.0)
    a[0,1]=-r**(-n-1)*v[9]; a[1,1]=r**(-n+1)*v[10]
    a[3,1]=-r**n*v[11]; a[4,1]=r**(n+2)*v[12]
    a[5,4]=-r**(n+1)
    a[2,5]=-r**(-n+1)/(2.0*rn+1.0); a[5,5]=r**(n+2)/(2.0*rn+1.0)
    b[0,0]=r**(-n)*rho*gra*v[1]; b[1,0]=-r**(-n+2)*rho*gra*v[3]
    b[3,0]=r**(n+1)*rho*gra*v[5]; b[4,0]=-r**(n+3)*rho*gra*v[7]
    b[0,2]=r**(-n)*v[13]; b[1,2]=-r**(-n+2)*v[14]
    b[3,2]=r**(n+1)*v[15]; b[4,2]=-r**(n+3)*v[16]
    b[0,3]=-r**(-n)*v[17]; b[1,3]=r**(-n+2)*v[18]
    b[3,3]=-r**(n+1)*v[19]; b[4,3]=r**(n+3)*v[20]
    b[0,4]=-rho*r**(-n)*v[21]; b[1,4]=rho*r**(-n+2)*v[22]
    b[3,4]=-rho*r**(n+1)*v[23]; b[4,4]=rho*r**(n+3)*v[24]
    return a, b


def matprod(n, rb, rd, rhu, za, grx, gry):
    """Product Y^{-1}(rd) * Y(rb) decomposed into ac, ad, bc, bd."""
    ac = np.zeros((6, 6)); ad = np.zeros((6, 6))
    bc = np.zeros((6, 6)); bd = np.zeros((6, 6))
    rn = float(n); x = rb; y = rd
    a1=rn/(2.0*(2.0*rn+3.0)); a2=1.0; a3=(rn+1.0)/(2.0*(2.0*rn-1.0)); a4=1.0
    b1=(rn+3.0)/(2.0*(2.0*rn+3.0)*(rn+1.0)); b2=1.0/rn
    b3=(-rn+2.0)/(2.0*rn*(2.0*rn-1.0)); b4=-1.0/(rn+1.0)
    c1=(rn*rn-rn-3.0)/(2.0*rn+3.0); c2=2.0*(rn-1.0)
    c3=(-rn*rn-3.0*rn+1.0)/(2.0*rn-1.0); c4=-2.0*(rn+2.0)
    d1=rn*(rn+2.0)/((2.0*rn+3.0)*(rn+1.0)); d2=2.0*(rn-1.0)/rn
    d3=(rn*rn-1.0)/(rn*(2.0*rn-1.0)); d4=2.0*(rn+2.0)/(rn+1.0)
    h1=rn+1.0; h2=1.0+2.0*rn; h3=2.0*rn-1.0; h4=3.0+2.0*rn; h5=rn-1.0
    v = np.zeros(25)
    v[1]=h1/h2; v[2]=-2.0*h1*(rn+2.0)/h2
    v[3]=rn*h1/2.0/h3/h2; v[4]=-(rn**2+3.0*rn-1.0)*rn/h2/h3
    v[5]=rn/h2; v[6]=2.0*rn*h5/h2; v[7]=rn*h1/2.0/h2/h4
    v[8]=h1*(rn**2-rn-3.0)/h2/h4; v[9]=-2.0*rn*h1*(2.0+rn)/h2
    v[10]=-h5*rn*h1*h1/h3/h2; v[11]=-2.0*h5*rn*h1/h2
    v[12]=-rn**2*h1*(2.0+rn)/h2/h4
    v[13]=-v[1]; v[14]=-v[3]; v[15]=-v[5]; v[16]=-v[7]
    v[17]=-rn*h1/h2; v[18]=(2.0-rn)*h1*rn/2.0/h3/h2
    v[19]=rn*h1/h2; v[20]=rn*h1*(3.0+rn)/2.0/h2/h4
    v[21]=-v[1]; v[22]=-v[3]; v[23]=-v[5]; v[24]=-v[7]
    xy=x/y; yx=y/x
    ac[0,0]=(a1*v[2]*xy**(n+1)-a2*v[4]*xy**(n-1)+a3*v[6]*yx**n-a4*v[8]*yx**(n+2))
    ac[0,1]=-(a1*v[9]*xy**(n+1)-a2*v[10]*xy**(n-1)+a3*v[11]*yx**n-a4*v[12]*yx**(n+2))
    ac[1,0]=(b1*v[2]*xy**(n+1)-b2*v[4]*xy**(n-1)+b3*v[6]*yx**n-b4*v[8]*yx**(n+2))
    ac[1,1]=-(b1*v[9]*xy**(n+1)-b2*v[10]*xy**(n-1)+b3*v[11]*yx**n-b4*v[12]*yx**(n+2))
    ta=xy**n-yx**(n+1)
    ac[2,0]=rhu*grx*ac[0,0]-(3.0*rhu*za*y/(2.0*rn+1.0))*ta
    ac[2,1]=rhu*grx*ac[0,1]; ac[2,4]=rhu*yx**(n+1)
    ac[2,5]=(rhu*y/(2.0*rn+1.0))*ta
    ac[4,0]=-(3.0*za*y/(2.0*rn+1.0))*ta; ac[4,4]=yx**(n+1)
    ac[4,5]=(y/(2.0*rn+1.0))*ta
    ac[5,0]=3.0*za*(a1*v[2]*xy**(n+1)-(1.0+a2*v[4])*xy**(n-1)+a3*v[6]*yx**n-a4*v[8]*yx**(n+2))
    ac[5,1]=3.0*za*ac[0,1]; ac[5,5]=xy**(n-1)
    ad[0,0]=rhu*gry*(a1*v[1]*x*xy**n-a2*v[3]*x*xy**(n-2)+a3*v[5]*y*yx**n-a4*v[7]*y*yx**(n+2))
    ad[0,2]=(a1*v[13]*x*xy**n-a2*v[14]*x*xy**(n-2)+a3*v[15]*y*yx**n-a4*v[16]*y*yx**(n+2))
    ad[0,3]=-(a1*v[17]*x*xy**n-a2*v[18]*x*xy**(n-2)+a3*v[19]*y*yx**n-a4*v[20]*y*yx**(n+2))
    ad[0,4]=-rhu*(a1*v[21]*x*xy**n-a2*v[22]*x*xy**(n-2)+a3*v[23]*y*yx**n-a4*v[24]*y*yx**(n+2))
    ad[1,0]=rhu*gry*(b1*v[1]*x*xy**n-b2*v[3]*x*xy**(n-2)+b3*v[5]*y*yx**n-b4*v[7]*y*yx**(n+2))
    ad[1,2]=(b1*v[13]*x*xy**n-b2*v[14]*x*xy**(n-2)+b3*v[15]*y*yx**n-b4*v[16]*y*yx**(n+2))
    ad[1,3]=-(b1*v[17]*x*xy**n-b2*v[18]*x*xy**(n-2)+b3*v[19]*y*yx**n-b4*v[20]*y*yx**(n+2))
    ad[1,4]=-rhu*(b1*v[21]*x*xy**n-b2*v[22]*x*xy**(n-2)+b3*v[23]*y*yx**n-b4*v[24]*y*yx**(n+2))
    ad[2,0]=rhu*grx*ad[0,0]; ad[2,2]=rhu*grx*ad[0,2]
    ad[2,3]=rhu*grx*ad[0,3]; ad[2,4]=rhu*grx*ad[0,4]
    ad[5,0]=3.0*za*ad[0,0]; ad[5,2]=3.0*za*ad[0,2]
    ad[5,3]=3.0*za*ad[0,3]; ad[5,4]=3.0*za*ad[0,4]
    bc[2,0]=(c1*v[2]*(1.0/y)*xy**n-c2*v[4]*(1.0/y)*xy**(n-2)+c3*v[6]*(1.0/x)*yx**n-c4*v[8]*(1.0/x)*yx**(n+2))
    bc[2,1]=-(c1*v[9]*(1.0/y)*xy**n-c2*v[10]*(1.0/y)*xy**(n-2)+c3*v[11]*(1.0/x)*yx**n-c4*v[12]*(1.0/x)*yx**(n+2))
    bc[3,0]=(d1*v[2]*(1.0/y)*xy**n-d2*v[4]*(1.0/y)*xy**(n-2)+d3*v[6]*(1.0/x)*yx**n-d4*v[8]*(1.0/x)*yx**(n+2))
    bc[3,1]=-(d1*v[9]*(1.0/y)*xy**n-d2*v[10]*(1.0/y)*xy**(n-2)+d3*v[11]*(1.0/x)*yx**n-d4*v[12]*(1.0/x)*yx**(n+2))
    bd[2,0]=rhu*gry*(c1*v[1]*xy**n-c2*v[3]*xy**(n-2)+c3*v[5]*yx**(n+1)-c4*v[7]*yx**(n+3))
    bd[2,2]=(c1*v[13]*xy**n-c2*v[14]*xy**(n-2)+c3*v[15]*yx**(n+1)-c4*v[16]*yx**(n+3))
    bd[2,3]=-(c1*v[17]*xy**n-c2*v[18]*xy**(n-2)+c3*v[19]*yx**(n+1)-c4*v[20]*yx**(n+3))
    bd[2,4]=-rhu*(c1*v[21]*xy**n-c2*v[22]*xy**(n-2)+c3*v[23]*yx**(n+1)-c4*v[24]*yx**(n+3))
    bd[3,0]=rhu*gry*(d1*v[1]*xy**n-d2*v[3]*xy**(n-2)+d3*v[5]*yx**(n+1)-d4*v[7]*yx**(n+3))
    bd[3,2]=(d1*v[13]*xy**n-d2*v[14]*xy**(n-2)+d3*v[15]*yx**(n+1)-d4*v[16]*yx**(n+3))
    bd[3,3]=-(d1*v[17]*xy**n-d2*v[18]*xy**(n-2)+d3*v[19]*yx**(n+1)-d4*v[20]*yx**(n+3))
    bd[3,4]=-rhu*(d1*v[21]*xy**n-d2*v[22]*xy**(n-2)+d3*v[23]*yx**(n+1)-d4*v[24]*yx**(n+3))
    return ac, ad, bc, bd


def corebo(n, r, ro, a_const):
    """Core-mantle boundary conditions."""
    g = np.zeros((6, 3))
    rn = float(n)
    g[0, 0] = -(r ** (n - 1)) / a_const
    g[0, 2] = 1.0; g[1, 1] = 1.0
    g[2, 2] = ro * a_const * r
    g[4, 0] = r ** n
    g[5, 0] = 2.0 * (rn - 1.0) * r ** (n - 1)
    g[5, 2] = 3.0 * a_const
    return g


def promat(cc_all, nv):
    """Polynomial product of propagator matrices."""
    ai = np.zeros((2 * nv + 1, 6, 6))
    ai[0:3] = cc_all[0]
    if nv == 1:
        return ai
    for i in range(1, nv):
        nn = 2 * (i + 1)
        ci = np.zeros((2 * nv + 1, 6, 6))
        bi = cc_all[i]
        for k in range(nn + 1):
            for ll in range(nn - 1):
                for j in range(3):
                    if ll + j == k:
                        ci[k] += ai[ll] @ bi[j]
        ai[:nn + 1] = ci[:nn + 1]
    return ai


def det_tu(rr, nv):
    """Secular polynomial coefficients from 3x3 polynomial matrix determinant."""
    max_deg = 3 * 2 * nv
    co = np.zeros(max_deg + 1)
    for inex in range(max_deg + 1):
        for k in range(2 * nv + 1):
            for ll in range(2 * nv + 1):
                for m in range(2 * nv + 1):
                    if k + ll + m == inex:
                        co[inex] += (rr[k,0,0]*rr[ll,1,1]*rr[m,2,2]
                                   - rr[k,0,0]*rr[ll,1,2]*rr[m,2,1]
                                   - rr[k,0,1]*rr[ll,1,0]*rr[m,2,2]
                                   + rr[k,0,1]*rr[ll,1,2]*rr[m,2,0]
                                   + rr[k,0,2]*rr[ll,1,0]*rr[m,2,1]
                                   - rr[k,0,2]*rr[ll,1,1]*rr[m,2,0])
    return co


def ded(a, b, c, d):
    return a * d - b * c


def compute_adjoint(mat):
    """Compute adjoint (cofactor transpose) of 3x3 matrix."""
    adj = np.zeros((3, 3))
    adj[0,0]=ded(mat[1,1],mat[1,2],mat[2,1],mat[2,2])
    adj[1,0]=-ded(mat[1,0],mat[1,2],mat[2,0],mat[2,2])
    adj[2,0]=ded(mat[1,0],mat[1,1],mat[2,0],mat[2,1])
    adj[0,1]=-ded(mat[0,1],mat[0,2],mat[2,1],mat[2,2])
    adj[1,1]=ded(mat[0,0],mat[0,2],mat[2,0],mat[2,2])
    adj[2,1]=-ded(mat[0,0],mat[0,1],mat[2,0],mat[2,1])
    adj[0,2]=ded(mat[0,1],mat[0,2],mat[1,1],mat[1,2])
    adj[1,2]=-ded(mat[0,0],mat[0,2],mat[1,0],mat[1,2])
    adj[2,2]=ded(mat[0,0],mat[0,1],mat[1,0],mat[1,1])
    return adj


def compute_spectrum(model):
    nv = model["nv"]
    radii = np.array(model["radii_m"], dtype=np.float64)
    rho = np.array(model["densities_kgm3"], dtype=np.float64)
    rmu = np.array(model["rigidities_Pa"], dtype=np.float64) / 1e11
    vis = np.array(model["viscosities_Pas"], dtype=np.float64) / 1e21
    lmin, lmax = model["lmin"], model["lmax"]
    i_loading = 1 if model.get("loading", True) else 0
    nl = nv + 1
    nroots = 4 * nv

    # Normalization (DEFPA)
    ggg = G_NEWTON
    t0 = KYR_IN_SECONDS
    xmass = 4.0*PI*rho[0]*radii[0]**3/3.0
    for k in range(1, nv + 2):
        xmass += (4.0/3.0)*PI*(radii[k]**3-radii[k-1]**3)*rho[k]
    g = np.zeros(nv + 2)
    g[0] = ggg*(4.0/3.0)*PI*rho[0]*radii[0]
    for k in range(1, nv + 2):
        mi = g[0]*radii[0]**2/ggg
        for j in range(1, k + 1):
            mi += (4.0/3.0)*PI*(radii[j]**3-radii[j-1]**3)*rho[j]
        g[k] = mi*ggg/radii[k]**2

    ra0 = radii[nl]; rhor = rho[1]; rig_norm = rmu[nl]
    r = radii / ra0
    rho_n = rho / rhor
    rmu_n = rmu / rig_norm
    vis_n = np.zeros(nv + 2)
    for k in range(nv + 2):
        if vis[k] > 0:
            vis_n[k] = vis[k] * 1e21 / (rig_norm * 1e11 * t0)
    ggg_n = G_NEWTON * rhor**2 * ra0**2 / (rig_norm * 1e11)
    g_n = np.zeros(nv + 2)
    g_n[0] = ggg_n*(4.0/3.0)*PI*rho_n[0]*r[0]
    for k in range(1, nv + 2):
        mi = g_n[0]*r[0]**2/ggg_n
        for j in range(1, k + 1):
            mi += (4.0/3.0)*PI*(r[j]**3-r[j-1]**3)*rho_n[j]
        g_n[k] = mi*ggg_n/r[k]**2
    aco = np.zeros(nv + 2)
    for k in range(nv + 2):
        aco[k] = (4.0*PI/3.0)*rho_n[k]*ggg_n
    xmass_n = 4.0*PI*rho_n[0]*r[0]**3/3.0
    for k in range(1, nv + 2):
        xmass_n += (4.0/3.0)*PI*(r[k]**3-r[k-1]**3)*rho_n[k]

    results = {d: {} for d in range(lmin, lmax + 1)}

    for l_deg in range(lmin, lmax + 1):
        cc_layers = []
        for k in range(1, nl):
            li = nl - k
            ac_m, ad_m, bc_m, bd_m = matprod(l_deg, r[li], r[li-1], rho_n[li], aco[li], g_n[li], g_n[li-1])
            mu_k = rmu_n[li]; vis_k = vis_n[li]
            k0 = ac_m + bd_m + bc_m * mu_k + ad_m / mu_k
            k1 = ad_m / vis_k
            k2 = bc_m * (-mu_k**2 / vis_k)
            cc = np.zeros((3, 6, 6))
            cc[0] = k1 * mu_k / vis_k
            cc[1] = k0 * mu_k / vis_k + k1 + k2
            cc[2] = k0
            cc_layers.append(cc)

        a_dir, b_dir = diretta(l_deg, r[nl], rho_n[nl], aco[nl], g_n[nl])
        c_inv, d_inv = inversa(l_deg, r[nl-1], rho_n[nl], aco[nl], g_n[nl-1])
        matela = (a_dir + rmu_n[nl] * b_dir) @ (c_inv + d_inv / rmu_n[nl])

        pj1 = np.zeros((3, 6)); pj2 = np.zeros((3, 6))
        pj1[0,0]=1.0; pj1[1,1]=1.0; pj1[2,4]=1.0
        pj2[0,2]=1.0; pj2[1,3]=1.0
        pj2[2, 5 if l_deg != 1 else 4] = 1.0

        sinist_2 = pj2 @ matela
        sinist_1 = pj1 @ matela

        coefmat = promat(cc_layers, nv)

        rrrr = np.zeros((2*nv+1, 3, 6))
        qqqq = np.zeros((2*nv+1, 3, 6))
        for inu in range(2*nv+1):
            rrrr[inu] = sinist_2 @ coefmat[inu]
            qqqq[inu] = sinist_1 @ coefmat[inu]

        cmb = corebo(l_deg, r[0], rho_n[0], aco[0])
        rr = np.zeros((2*nv+1, 3, 3))
        qq = np.zeros((2*nv+1, 3, 3))
        for inu in range(2*nv+1):
            rr[inu] = rrrr[inu] @ cmb
            qq[inu] = qqqq[inu] @ cmb

        co = det_tu(rr, nv)

        aa = np.zeros(nroots + 1)
        for i in range(nroots + 1):
            aa[i] = co[6*nv - i]
        poly_for_roots = aa[::-1]

        physical_modes = []
        if abs(poly_for_roots[0]) > 1e-60:
            roots = np.roots(poly_for_roots)
            for root in roots:
                rt1, rt2 = root.real, root.imag
                thresh = max(1e-8, abs(rt1) * 1e-6)
                if abs(rt2) < thresh and rt1 < -1e-15:
                    physical_modes.append(1.0 / rt1)
        physical_modes.sort(key=lambda x: abs(x))

        gamma = (2.0*l_deg+1.0)/(4.0*PI*r[nl]**2)
        bcs = np.zeros(3)
        if i_loading == 1:
            bcs[0] = -g_n[nl] * gamma
            if l_deg != 1:
                bcs[2] = -4.0*PI*ggg_n*gamma
        else:
            bcs[2] = -4.0*PI*ggg_n*gamma

        rr_lead = rr[2*nv]; qq_lead = qq[2*nv]
        adj_lead = compute_adjoint(rr_lead)
        qr_lead = qq_lead @ adj_lead
        det_lead = co[6*nv]
        x_el = qr_lead @ bcs / det_lead

        h_e = x_el[0] * xmass_n / r[nl]
        l_e = x_el[1] * xmass_n / r[nl]
        k_e = -1.0 - (xmass_n / r[nl] / g_n[nl]) * x_el[2]

        ctmp = np.zeros(3*2*nv)
        for ii in range(3*2*nv):
            ctmp[ii] = co[ii+1] * float(ii+1)

        h_v_list, l_v_list, k_v_list = [], [], []
        for s_val in physical_modes:
            r_r_m = rr[2*nv].copy(); q_q_m = qq[2*nv].copy()
            for kk in range(2*nv-1, -1, -1):
                r_r_m = r_r_m * s_val + rr[kk]
                q_q_m = q_q_m * s_val + qq[kk]
            adj_m = compute_adjoint(r_r_m)
            qr_m = q_q_m @ adj_m

            derpo = ctmp[3*2*nv-1]
            for k in range(3*2*nv-2, -1, -1):
                derpo = derpo * s_val + ctmp[k]

            xx = qr_m @ bcs
            h_v_list.append(float(xx[0]/derpo * xmass_n/r[nl]))
            l_v_list.append(float(xx[1]/derpo * xmass_n/r[nl]))
            k_v_list.append(float(-(xmass_n/r[nl]/g_n[nl]) * xx[2]/derpo))

        h_f = h_e - sum(hv/s for hv, s in zip(h_v_list, physical_modes))
        l_f = l_e - sum(lv/s for lv, s in zip(l_v_list, physical_modes))
        k_f = k_e - sum(kv/s for kv, s in zip(k_v_list, physical_modes))

        results[l_deg] = {
            'h_e': float(h_e), 'l_e': float(l_e), 'k_e': float(k_e),
            'h_f': float(h_f), 'l_f': float(l_f), 'k_f': float(k_f),
            'modes': physical_modes,
            'h_v': h_v_list, 'l_v': l_v_list, 'k_v': k_v_list,
        }

    degrees = list(range(lmin, lmax + 1))
    return {
        "degrees": degrees,
        "elastic": {
            "h": [results[d]['h_e'] for d in degrees],
            "l": [results[d]['l_e'] for d in degrees],
            "k": [results[d]['k_e'] for d in degrees],
        },
        "fluid": {
            "h": [results[d]['h_f'] for d in degrees],
            "l": [results[d]['l_f'] for d in degrees],
            "k": [results[d]['k_f'] for d in degrees],
        },
        "spectrum": {str(d): results[d]['modes'] for d in degrees},
        "residues": {
            "h": {str(d): results[d]['h_v'] for d in degrees},
            "l": {str(d): results[d]['l_v'] for d in degrees},
            "k": {str(d): results[d]['k_v'] for d in degrees},
        },
    }


def main():
    config = parse_taboo_config("/app/data/earth_model.dat")
    model = build_model(config)
    output = compute_spectrum(model)
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
