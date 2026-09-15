% validate_constants.m - Reference equilibrium constants for marine carbonate chemistry
% Usage: octave --no-gui --eval "T=25; S=35; run('/app/validate_constants.m')"
%   or:  octave --no-gui --eval "T=2; S=34.7; P=3000; run('/app/validate_constants.m')"
%
% Outputs equilibrium constants at 1 atm. If P (dbar) is set and > 0,
% also outputs pressure correction coefficients and corrected values.
%
% Constants follow the same formulations used by PyCO2SYS with:
%   opt_k_carbonic=10, opt_k_bisulfate=1, opt_k_fluoride=1, opt_total_borate=1
%

TK = T + 273.15;

% --- K1, K2: Lueker et al. 2000 (Total pH scale) ---
pK1 = 3633.86/TK - 61.2172 + 9.6777*log(TK) - 0.011555*S + 0.0001152*S^2;
pK2 = 471.78/TK + 25.929 - 3.16967*log(TK) - 0.01781*S + 0.0001122*S^2;
K1 = 10^(-pK1);
K2 = 10^(-pK2);

% --- KSO4: Dickson 1990 (Free pH scale) ---
IonS = 19.924 * S / (1000.0 - 1.005 * S);
sqrtI = sqrt(IonS);
lnKSO4 = 141.328 - 4276.1/TK - 23.093*log(TK) ...
    + (-13856.0/TK + 324.57 - 47.986*log(TK))*sqrtI ...
    + (35474.0/TK - 771.54 + 114.723*log(TK))*IonS ...
    - 2698.0/TK * IonS^1.5 ...
    + 1776.0/TK * IonS^2 ...
    + log(1.0 - 0.001005*S);
KSO4 = exp(lnKSO4);

% --- KF: Dickson & Riley 1979 (Free pH scale) ---
lnKF = 1590.2/TK - 12.641 + 1.525*sqrtI;
KF = exp(lnKF) * (1.0 - 0.001005*S);

% --- KB: Dickson 1990 (Total pH scale) ---
sqrtS = sqrt(S);
lnKB = (-8966.90 - 2890.53*sqrtS - 77.942*S + 1.728*S^1.5 - 0.0996*S^2)/TK ...
    + 148.0248 + 137.1942*sqrtS + 1.62142*S ...
    + (-24.4344 - 25.085*sqrtS - 0.2474*S)*log(TK) ...
    + 0.053105*sqrtS*TK;
KB = exp(lnKB);

% --- KW: Millero 1995 (SWS pH scale) ---
lnKW = 148.9652 - 13847.26/TK - 23.6521*log(TK) ...
    + (-5.977 + 118.67/TK + 1.0495*log(TK))*sqrtS ...
    - 0.01615*S;
KW = exp(lnKW);

fprintf('=== Constants at 1 atm (T=%.2f C, S=%.3f) ===\n', T, S);
fprintf('K1 = %.12e\n', K1);
fprintf('K2 = %.12e\n', K2);
fprintf('KB = %.12e\n', KB);
fprintf('KW = %.12e\n', KW);
fprintf('KSO4 = %.12e\n', KSO4);
fprintf('KF = %.12e\n', KF);

% --- Pressure correction coefficients (Millero 1995) ---
fprintf('\n=== Pressure correction coefficients (Millero 1995) ===\n');
fprintf('K1:   dV = -25.50 + 0.1271*T + 0.0*T^2\n');
fprintf('      dK = (-3.08 + 0.0877*T)*1e-3\n');
fprintf('K2:   dV = -15.82 + (-0.0219)*T + 0.0*T^2\n');
fprintf('      dK = (1.13 + (-0.1475)*T)*1e-3\n');
fprintf('KB:   dV = -29.48 + 0.1622*T + (-0.002608)*T^2\n');
fprintf('      dK = (-2.84 + 0.0*T)*1e-3\n');
fprintf('KW:   dV = -25.60 + 0.2324*T + (-0.0036246)*T^2\n');
fprintf('      dK = (-5.13 + 0.0794*T)*1e-3\n');
fprintf('KSO4: dV = -18.03 + 0.0466*T + 0.000316*T^2\n');
fprintf('      dK = (-4.53 + 0.09*T)*1e-3\n');
fprintf('KF:   dV = -9.78 + (-0.0090)*T + (-0.000942)*T^2\n');
fprintf('      dK = (-3.91 + 0.054*T)*1e-3\n');

% --- Pressure-corrected constants (if P is defined and > 0) ---
if exist('P', 'var') && P > 0
    P_bar = P / 10.0;
    R = 83.14472;

    % K1
    dV_K1 = -25.50 + 0.1271*T;
    dK_K1 = (-3.08 + 0.0877*T) * 1e-3;
    K1_p = K1 * exp((-dV_K1 + 0.5*dK_K1*P_bar)*P_bar/(R*TK));

    % K2
    dV_K2 = -15.82 + (-0.0219)*T;
    dK_K2 = (1.13 + (-0.1475)*T) * 1e-3;
    K2_p = K2 * exp((-dV_K2 + 0.5*dK_K2*P_bar)*P_bar/(R*TK));

    % KB
    dV_KB = -29.48 + 0.1622*T + (-0.002608)*T^2;
    dK_KB = (-2.84 + 0.0*T) * 1e-3;
    KB_p = KB * exp((-dV_KB + 0.5*dK_KB*P_bar)*P_bar/(R*TK));

    % KW
    dV_KW = -25.60 + 0.2324*T + (-0.0036246)*T^2;
    dK_KW = (-5.13 + 0.0794*T) * 1e-3;
    KW_p = KW * exp((-dV_KW + 0.5*dK_KW*P_bar)*P_bar/(R*TK));

    % KSO4
    dV_KSO4 = -18.03 + 0.0466*T + 0.000316*T^2;
    dK_KSO4 = (-4.53 + 0.09*T) * 1e-3;
    KSO4_p = KSO4 * exp((-dV_KSO4 + 0.5*dK_KSO4*P_bar)*P_bar/(R*TK));

    % KF
    dV_KF = -9.78 + (-0.0090)*T + (-0.000942)*T^2;
    dK_KF = (-3.91 + 0.054*T) * 1e-3;
    KF_p = KF * exp((-dV_KF + 0.5*dK_KF*P_bar)*P_bar/(R*TK));

    fprintf('\n=== Pressure-corrected (P=%.0f dbar = %.1f bar) ===\n', P, P_bar);
    fprintf('K1_p = %.12e\n', K1_p);
    fprintf('K2_p = %.12e\n', K2_p);
    fprintf('KB_p = %.12e\n', KB_p);
    fprintf('KW_p = %.12e\n', KW_p);
    fprintf('KSO4_p = %.12e\n', KSO4_p);
    fprintf('KF_p = %.12e\n', KF_p);
end
