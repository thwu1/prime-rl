"""Generate initial conditions for the magnetized vortex test problem in HDF5 format."""
import numpy as np
import h5py

N = 128
boxsize = 1.0
gamma = 5.0 / 3.0
dx = boxsize / N

# Cell centers
xlin = np.linspace(0.5 * dx, boxsize - 0.5 * dx, N)
Y, X = np.meshgrid(xlin, xlin)

# Node positions (top-right corner of each cell)
xlin_node = np.linspace(dx, boxsize, N)
Yn, Xn = np.meshgrid(xlin_node, xlin_node)

# Primitive variables
rho = (gamma**2 / (4 * np.pi)) * np.ones(X.shape)
vx = -np.sin(2 * np.pi * Y)
vy = np.sin(2 * np.pi * X)
P_gas = (gamma / (4 * np.pi)) * np.ones(X.shape)

# Magnetic vector potential at nodes
Az = (np.cos(4 * np.pi * Xn) / (4 * np.pi * np.sqrt(4 * np.pi))
      + np.cos(2 * np.pi * Yn) / (2 * np.pi * np.sqrt(4 * np.pi)))

# Curl of vector potential -> face-centered B
R = -1
L = 1
bx_face = (Az - np.roll(Az, L, axis=1)) / dx
by_face = -(Az - np.roll(Az, L, axis=0)) / dx

with h5py.File('/app/initial_conditions.h5', 'w') as f:
    f.attrs['N'] = N
    f.attrs['boxsize'] = boxsize
    f.attrs['dx'] = dx
    f.attrs['gamma'] = gamma
    f.create_dataset('rho', data=rho)
    f.create_dataset('vx', data=vx)
    f.create_dataset('vy', data=vy)
    f.create_dataset('P_gas', data=P_gas)
    f.create_dataset('bx_face', data=bx_face)
    f.create_dataset('by_face', data=by_face)

print("Initial conditions written to /app/initial_conditions.h5")
