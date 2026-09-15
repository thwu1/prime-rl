within;
model CHPSteamNetwork
  "Combined heat and power steam/water distribution network for data reconciliation"

  // Thermodynamic property: specific enthalpy of water
  function specificEnthalpy
    "Polynomial approximation h(T) [kJ/kg] for water, T in degC"
    input Real T "Temperature (degrees Celsius)";
    output Real h "Specific enthalpy (kJ/kg)";
  protected
    constant Real a = 4.18 "Linear coefficient [kJ/(kg*K)]";
    constant Real b = 0.00062 "Quadratic coefficient [kJ/(kg*K^2)]";
  algorithm
    h := a * T + b * T ^ 2;
  end specificEnthalpy;

  // ---- Mass flow rates [kg/s] ----
  Real m1(uncertain = Uncertainty.refine) "Boiler 1 steam output";
  Real m2(uncertain = Uncertainty.refine) "Boiler 2 steam output";
  Real m3(uncertain = Uncertainty.refine) "Main header combined flow";
  Real m4(uncertain = Uncertainty.refine) "Process A steam supply";
  Real m5(uncertain = Uncertainty.refine) "Process B steam supply";
  Real m6(uncertain = Uncertainty.refine) "Process C steam supply";
  Real m7(uncertain = Uncertainty.refine) "Process A condensate return";
  Real m8(uncertain = Uncertainty.refine) "Process B condensate return";
  Real m9(uncertain = Uncertainty.refine) "Process C condensate return";
  Real m10(uncertain = Uncertainty.refine) "Makeup water inlet";
  Real m11(uncertain = Uncertainty.refine) "Return header outlet";
  Real m12(uncertain = Uncertainty.refine) "Pump station discharge";

  // ---- Temperatures [degC] ----
  Real T1(uncertain = Uncertainty.refine) "Boiler 1 outlet temperature";
  Real T2(uncertain = Uncertainty.refine) "Boiler 2 outlet temperature";
  Real T3(uncertain = Uncertainty.refine) "Main header temperature";
  Real T7(uncertain = Uncertainty.refine) "Process A return temperature";
  Real T8(uncertain = Uncertainty.refine) "Process B return temperature";
  Real T9(uncertain = Uncertainty.refine) "Process C return temperature";
  Real T10(uncertain = Uncertainty.refine) "Makeup water temperature";
  Real T11(uncertain = Uncertainty.refine) "Return header outlet temperature";

equation
  // --- Mass balances ---
  m1 + m2 = m3;                                    // Boiler header mixing
  m3 = m4 + m5 + m6;                               // Main distributor split
  m4 = m7;                                          // Process A steady-state
  m5 = m8;                                          // Process B steady-state
  m6 = m9;                                          // Process C steady-state
  m7 + m8 + m9 + m10 = m11;                        // Return header collection
  m11 = m12;                                        // Pump station continuity

  // --- Energy balances (adiabatic mixing) ---
  m1 * specificEnthalpy(T1) + m2 * specificEnthalpy(T2) = m3 * specificEnthalpy(T3);
  m7 * specificEnthalpy(T7) + m8 * specificEnthalpy(T8) + m9 * specificEnthalpy(T9) + m10 * specificEnthalpy(T10) = m11 * specificEnthalpy(T11);

  annotation(
    Documentation(info="<html>
      <p>Combined heat and power plant steam/water distribution network.</p>
      <p>Two boilers feed a main steam header, which distributes to three
      process heat exchangers. Process condensate returns and makeup water
      are collected in a return header, then pumped back to the boilers.</p>
      <p>Network topology: 20 measured variables (12 mass flow, 8 temperature),
      9 conservation constraints (7 mass balance, 2 energy balance).</p>
    </html>"),
    experiment(StopTime = 0, Interval = 1)
  );
end CHPSteamNetwork;
