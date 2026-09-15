/* Selene Mission Context
 * Mission profile, use cases, operational scenarios, and state machines.
 *
 *
 * This package defines the mission operations concept that drives
 * the staging sequence used in delta-v analysis. The staging
 * order is critical: the transfer vehicle fires FIRST while mated
 * to the full stack, then separates, and the lander fires
 * independently for descent.
 */

package SeleneMissionContext {

    import SeleneArchitecture::seleneSystem;
    import SeleneRequirements::*;

    doc /* Selene Lunar Cargo Delivery System
         *
         * Mission: Deliver scientific instruments and infrastructure
         * payloads to the lunar south pole region in support of
         * sustained human lunar exploration.
         *
         * Target: Shackleton Crater rim, 89.9°S 0.0°E
         * Launch Vehicle: Atlas V 551 or equivalent
         * Transfer Duration: 4.5 days (direct transfer)
         * Surface Mission Duration: 14 Earth days (1 lunar day)
         *
         * Mission Profile:
         *   Phase 1 - Transfer: The transfer vehicle performs
         *     trans-lunar injection and lunar orbit insertion burns.
         *     Combined delta-v budget: approximately 1200 m/s.
         *     The full stack (TV + Lander) is the initial mass
         *     for the transfer vehicle's burn.
         *   Phase 2 - Separation: Transfer vehicle jettisoned
         *     after lunar orbit insertion complete. The lander
         *     continues independently from this point.
         *   Phase 3 - Descent: Lander performs powered descent
         *     from 100 km circular lunar orbit to surface.
         *     Delta-v budget: approximately 3700 m/s including
         *     gravity losses, hover, and landing margin.
         *     The lander-only mass is the initial mass for descent.
         *   Phase 4 - Surface Ops: Payload deployed and
         *     commissioned on the lunar surface.
         *
         * STAGING SEQUENCE FOR DELTA-V ANALYSIS:
         * ═══════════════════════════════════════
         *   Step 1: TV ignites. Initial mass = TOTAL system mass
         *           (TV + Lander together). TV propellant is consumed.
         *           Final mass = total mass minus TV propellant mass.
         *   Step 2: TV separates. Only the lander continues.
         *   Step 3: Lander ignites. Initial mass = LANDER mass only
         *           (not the full stack). Lander propellant is consumed.
         *           Final mass = lander mass minus lander propellant.
         *
         * This two-stage sequence means the TV must accelerate
         * the entire stack but the lander only accelerates itself.
         */

    /* ---- Primary Use Case ---- */

    use case def DeliverPayloadToMoon {
        doc /* Primary mission use case: safely deliver cargo
               to a designated site on the lunar surface with
               precision landing within 100 meters of target.
               Success criteria:
                 - All payload delivered intact
                 - Landing within 100m of designated site
                 - Communication established within 1 hour
                 - Payload deployed within 24 hours */
        subject seleneSystem;
    }

    use case def PerformLunarOrbitInsertion {
        doc /* Transfer vehicle performs the main braking burn
               to capture into a 100 km circular lunar orbit.
               This is the primary delta-v maneuver for the TV. */
        subject seleneSystem;
        include use case DeliverPayloadToMoon;
    }

    use case def PerformPrecisionLanding {
        doc /* Lander performs autonomous hazard detection and
               avoidance during terminal descent to achieve
               precision landing at the target site. */
        subject seleneSystem;
        include use case DeliverPayloadToMoon;
    }

    /* ---- Mission Action Decomposition ---- */

    action def PerformSeleneMission {
        doc /* Top-level mission action decomposition showing
               the sequential phases of the Selene mission. Each
               action corresponds to a mission phase with specific
               mass and delta-v implications for analysis. */

        action performTransferBurns {
            doc /* Transfer vehicle ignites and performs the
                   trans-lunar injection burn followed by mid-course
                   corrections and lunar orbit insertion. Consumes
                   all transfer vehicle propellant.

                   Mass accounting:
                     Initial mass = seleneSystem total mass
                                  = transferVehicle + lander
                     Consumed = tvPropellant.mass (isConsumable=true)
                     Final mass = initial - consumed

                   This is a single-stage burn with no jettison
                   events during the transfer phase. */
        }

        then action separateTransferVehicle {
            doc /* Pyrotechnic bolts fire to separate the transfer
                   vehicle from the lander in lunar orbit. Only
                   the lander continues from this point. The TV
                   becomes orbital debris.

                   Mass accounting:
                     Lander mass = lander subtree total mass
                     TV mass is discarded (not counted in
                     lander delta-v calculation) */
        }

        then action performOrbitalPhasing {
            doc /* Lander performs minor orbit-adjust maneuvers
                   to align the ground track with the landing site.
                   Delta-v for phasing is included in the lander's
                   total delta-v budget but is small (<50 m/s). */
        }

        then action performPoweredDescent {
            doc /* Lander performs deorbit burn, powered braking,
                   approach phase, pitch-up, and terminal descent
                   to the surface. Initial mass is lander-only.

                   Mass accounting:
                     Initial mass = lander subtree total mass
                     Consumed = lnPropellant.mass (isConsumable=true)
                     Final mass = lander mass - consumed

                   The descent has four sub-phases:
                     1. Deorbit burn (small impulse)
                     2. Powered braking (main burn, ~90% of dv)
                     3. Approach and hazard avoidance
                     4. Terminal descent and touchdown */
        }

        then action deployPayloadOnSurface {
            doc /* Payload egress mechanisms activate and payload
                   is deployed and commissioned on the lunar
                   surface for science operations.

                   No propulsion involved. Power system transitions
                   from descent mode to surface operations mode.
                   Solar arrays deploy if stowed during descent. */
        }

        then action performSurfaceOperations {
            doc /* 14-day surface mission phase. Payload operates
                   autonomously with periodic communication windows
                   via direct-to-Earth link. Power system manages
                   day/night cycle using solar arrays and batteries. */
        }
    }

    /* ---- Mission State Machine ---- */

    state def SeleneMissionStateMachine {
        doc /* State machine capturing the mission phase transitions
               and their triggers. Each state corresponds to a
               distinct operational configuration of the system. */

        entry; then prelaunch;

        state prelaunch {
            doc /* Vehicle is on the launch pad, connected to
                   ground support equipment via umbilical. Internal
                   power, ground-commanded mode. */
            entry action initializeSystems;
        }

        transition prelaunch_to_ascent
            first prelaunch then ascent
            trigger liftoffDetected;

        state ascent {
            doc /* Launch vehicle ascent phase. Selene is a
                   passive payload during this phase. */
        }

        transition ascent_to_separation
            first ascent then lvSeparation
            trigger lvSeparationCommand;

        state lvSeparation {
            doc /* Separation from launch vehicle. Selene
                   becomes a free-flying spacecraft. Solar
                   arrays deploy, attitude control activates. */
            entry action deploySolarArrays;
            entry action activateAttitudeControl;
        }

        transition lvSep_to_transfer
            first lvSeparation then transfer
            trigger solarArraysDeployed;

        state transfer {
            doc /* Trans-lunar coast and TV burns. System mass
                   is full stack. TV propulsion is active. */
            do action performTransferBurns;
        }

        transition transfer_to_tvSep
            first transfer then tvSeparation
            trigger tvPropellantDepleted;

        state tvSeparation {
            doc /* Transfer vehicle separation. Pyrotechnics fire,
                   TV is jettisoned. Lander becomes independent. */
            entry action fireSeparationPyros;
        }

        transition tvSep_to_descent
            first tvSeparation then descent
            trigger separationConfirmed;

        state descent {
            doc /* Powered descent from lunar orbit to surface.
                   Lander propulsion is active. Initial mass is
                   lander-only. */
            do action performPoweredDescent;
        }

        transition descent_to_landed
            first descent then landed
            trigger touchdownDetected;

        state landed {
            doc /* Surface operations phase. Payload deployment
                   and commissioning. */
            entry action deployPayload;
            do action performSurfaceOperations;
        }
    }

    /* ---- Environmental Conditions ---- */

    package LunarEnvironment {
        doc /* Reference lunar environment parameters used in
               thermal and power analyses. These are not part of
               the spacecraft model but inform analysis boundary
               conditions. */

        attribute lunarSurfaceGravity : Real = 1.625;
        attribute lunarOrbitalVelocity100km : Real = 1633.0;
        attribute solarConstant1AU : Real = 1361.0;
        attribute lunarAlbedo : Real = 0.12;
        attribute lunarIRFlux : Real = 1268.0;
        attribute maxSurfaceTemp : Real = 400.0;
        attribute minSurfaceTemp : Real = 100.0;
        attribute lunarDayDuration : Real = 1209600.0;
    }
}
