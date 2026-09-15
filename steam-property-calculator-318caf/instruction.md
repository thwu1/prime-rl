A partial IAPWS-IF97 implementation is provided at `/app/src/` as C source files. The API is declared in `/app/src/if97_core.h`. A Makefile is provided but may need corrections. Published verification values are at `/app/data/verification.csv`.

Produce an executable at `/app/if97` supporting these CLI modes:

- `./if97 region <T_K> <P_MPa>` — print integer region number (1, 2, 3, or 5)
- `./if97 props <T_K> <P_MPa>` — print 7 space-separated values: v h u s cp cv w
- `./if97 satT <T_K>` — print saturation pressure (MPa)
- `./if97 satP <P_MPa>` — print saturation temperature (K)
- `./if97 backward_ph <P_MPa> <h_kJ/kg>` — print temperature T (K)
- `./if97 backward_ps <P_MPa> <s_kJ/(kg*K)>` — print temperature T (K)

Properties: v (m^3/kg), h (kJ/kg), u (kJ/kg), s (kJ/(kg*K)), cp (kJ/(kg*K)), cv (kJ/(kg*K)), w (m/s).

Region coverage:
- Region 1: 273.15 <= T <= 623.15 K, Psat(T) <= P <= 100 MPa
- Region 2: 273.15 <= T <= 1073.15 K, 0 < P <= Psat(T) or P <= 100 MPa above 623.15 K via B23 boundary
- Region 3: supercritical zone, (T, P) input, density must be solved numerically
- Region 5: 1073.15 < T <= 2273.15 K, 0 < P <= 50 MPa
- Backward equations T(P,h) and T(P,s) for Regions 1 and 2 (Region 2 requires subregion dispatch to 2a/2b/2c)

The C source must be compiled into a shared object (`libif97.so`) at `/app/src/libif97.so` and its exported functions called at runtime for the functionality it provides. Regions and equations not present in the C source must be implemented separately.

All outputs must match IAPWS verification values to 6 significant figures (relative tolerance 5e-7), except Region 3 forward properties (relative tolerance 5e-4).
