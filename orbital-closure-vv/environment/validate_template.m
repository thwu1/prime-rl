% Analytical Orbital Mechanics Validation Script
% ================================================
% Complete this script to compute analytical J2 secular perturbation rates
% and orbital mechanics reference values for cross-validation.
%
% Usage: octave --no-gui validate.m > /app/octave_results.txt
%
% Instructions:
%   1. Extract spacecraft initial state from the LEO GMAT script
%   2. Fill in the state vector components below
%   3. The script will compute analytical J2 secular rates and orbital parameters

% --- Physical Constants ---
mu_earth = 398600.4415;     % km^3/s^2
R_earth  = 6378.137;        % km
J2       = 1.08262668355e-3;

% --- Spacecraft Initial State (ECI Cartesian) ---
% TODO: Fill these in from the LEO GMAT script
X0  = 0.0;   % km
Y0  = 0.0;
Z0  = 0.0;
VX0 = 0.0;   % km/s
VY0 = 0.0;
VZ0 = 0.0;

% --- Compute Orbital Elements from Cartesian State ---
r_vec = [X0; Y0; Z0];
v_vec = [VX0; VY0; VZ0];
r_mag = norm(r_vec);
v_mag = norm(v_vec);

% Angular momentum vector
h_vec = cross(r_vec, v_vec);
h_mag = norm(h_vec);

% Semi-major axis (vis-viva equation)
energy = v_mag^2 / 2 - mu_earth / r_mag;
a = -mu_earth / (2 * energy);

% Eccentricity vector
e_vec = (1/mu_earth) * ((v_mag^2 - mu_earth/r_mag) * r_vec - dot(r_vec, v_vec) * v_vec);
ecc = norm(e_vec);

% Inclination
inc = acos(h_vec(3) / h_mag);

% Node vector
k_hat = [0; 0; 1];
n_vec = cross(k_hat, h_vec);
n_mag = norm(n_vec);

% RAAN (Right Ascension of Ascending Node)
if n_mag > 1e-10
  RAAN = acos(n_vec(1) / n_mag);
  if n_vec(2) < 0
    RAAN = 2*pi - RAAN;
  end
else
  RAAN = 0;
end

% --- Mean motion ---
n_motion = sqrt(mu_earth / a^3);

% --- J2 Secular Perturbation Rates ---
% RAAN precession: dOmega/dt = -3/2 * n * J2 * (Re/a)^2 * cos(i) / (1-e^2)^2
p = a * (1 - ecc^2);
dOmega_dt = -1.5 * n_motion * J2 * (R_earth/p)^2 * cos(inc);

% Convert to deg/day
dOmega_deg_day = dOmega_dt * (180/pi) * 86400;

% Argument of perigee precession:
% domega/dt = 3/2 * n * J2 * (Re/p)^2 * (2 - 5/2 * sin^2(i))
domega_dt = 1.5 * n_motion * J2 * (R_earth/p)^2 * (2 - 2.5 * sin(inc)^2);
domega_deg_day = domega_dt * (180/pi) * 86400;

% Orbital period
T_period = 2 * pi / n_motion;

% Apogee and perigee
r_apogee = a * (1 + ecc);
r_perigee = a * (1 - ecc);
alt_apogee = r_apogee - R_earth;
alt_perigee = r_perigee - R_earth;

% --- Output Results ---
printf("ORBITAL_ANALYSIS_RESULTS\n");
printf("semi_major_axis_km=%.10f\n", a);
printf("eccentricity=%.15e\n", ecc);
printf("inclination_deg=%.10f\n", inc * 180/pi);
printf("raan_deg=%.10f\n", RAAN * 180/pi);
printf("mean_motion_rad_s=%.15e\n", n_motion);
printf("orbital_period_s=%.6f\n", T_period);
printf("specific_energy_km2_s2=%.15e\n", energy);
printf("angular_momentum_km2_s=%.10f\n", h_mag);
printf("raan_precession_rad_s=%.15e\n", dOmega_dt);
printf("raan_precession_deg_day=%.10f\n", dOmega_deg_day);
printf("arg_perigee_precession_deg_day=%.10f\n", domega_deg_day);
printf("apogee_altitude_km=%.6f\n", alt_apogee);
printf("perigee_altitude_km=%.6f\n", alt_perigee);
printf("ANALYSIS_COMPLETE\n");
