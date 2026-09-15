package Requirements {
    private import ScalarValues::*;

    /* ===== Requirement Type Definitions ===== */

    requirement def MassRequirement {
        attribute massActual : Real;
        attribute massLimit : Real;
        require constraint { massActual <= massLimit }
    }

    requirement def PowerRequirement {
        attribute powerOutput : Real;
        attribute powerMinimum : Real;
        require constraint { powerOutput >= powerMinimum }
    }

    requirement def LifetimeRequirement {
        attribute lifetime : Real;
        attribute minimumLifetime : Real;
        require constraint { lifetime >= minimumLifetime }
    }

    requirement def DataRateRequirement {
        attribute rateActual : Real;
        attribute rateMinimum : Real;
        require constraint { rateActual >= rateMinimum }
    }

    /* ===== System-Level Requirements ===== */

    requirement <'REQ-SYS-001'> systemMassReq : MassRequirement {
        doc /* Total satellite mass shall not exceed 250 kg.
             * This includes all subsystems, harness, and margin. */
        attribute redefines massLimit = 250.0;
    }

    requirement <'REQ-SYS-002'> systemPowerReq : PowerRequirement {
        doc /* Total power generation shall exceed 800 W
             * at end-of-life conditions. */
        attribute redefines powerMinimum = 800.0;
    }

    requirement <'REQ-SYS-003'> missionLifetimeReq : LifetimeRequirement {
        doc /* Mission lifetime shall be at least 5 years
             * with provisions for extended operations. */
        attribute redefines minimumLifetime = 5.0;
    }

    requirement <'REQ-SYS-004'> downlinkRateReq : DataRateRequirement {
        doc /* Data downlink rate shall exceed 100 Mbps
             * for science data transmission via X-band. */
        attribute redefines rateMinimum = 100.0;
    }

    /* ===== Payload Requirements ===== */

    requirement <'REQ-PAY-001'> opticalResolutionReq {
        doc /* Optical imager ground sample distance shall
             * be 0.5 meters or better at nadir. */
        attribute resolution : Real;
        require constraint { resolution <= 0.5 }
    }

    requirement <'REQ-PAY-002'> sarSwathReq {
        doc /* SAR imaging swath width shall be at least
             * 20 km in stripmap mode. */
        attribute swathWidth : Real;
        require constraint { swathWidth >= 20.0 }
    }

    requirement <'REQ-PAY-003'> dataStorageReq {
        doc /* On-board data storage capacity shall
             * exceed 1 TB for mission data buffering. */
        attribute storageCapacity : Real;
        require constraint { storageCapacity >= 1.0 }
    }

    /* ===== Power Requirements ===== */

    requirement <'REQ-PWR-001'> batteryCapacityReq {
        doc /* Battery pack capacity shall exceed 30 Ah
             * to support eclipse operations. */
        attribute capacity : Real;
        require constraint { capacity >= 30.0 }
    }

    requirement <'REQ-PWR-002'> solarEfficiencyReq {
        doc /* Solar array cell efficiency shall exceed 28%
             * using triple-junction GaAs technology. */
        attribute efficiency : Real;
        require constraint { efficiency >= 0.28 }
    }

    /* ===== ADCS Requirements ===== */

    requirement <'REQ-ADC-001'> pointingAccuracyReq {
        doc /* Spacecraft pointing accuracy shall be within
             * 0.01 degrees (3-sigma) in all axes. */
        attribute accuracy : Real;
        require constraint { accuracy <= 0.01 }
    }

    requirement <'REQ-ADC-002'> slewRateReq {
        doc /* Spacecraft slew rate shall exceed 1 degree
             * per second for agile imaging operations. */
        attribute slewRate : Real;
        require constraint { slewRate >= 1.0 }
    }

    /* ===== Communications Requirements ===== */

    requirement <'REQ-COM-001'> sBandUplinkReq {
        doc /* S-band uplink capability required for
             * telecommand reception at any orbit position. */
    }

    requirement <'REQ-COM-002'> xBandDownlinkReq {
        doc /* X-band downlink capability required for
             * high-rate science data transmission. */
    }

    /* ===== Propulsion Requirements ===== */

    requirement <'REQ-PRO-001'> deltaVReq {
        doc /* Total delta-V capability shall exceed 150 m/s
             * for orbit maintenance over mission lifetime. */
        attribute deltaV : Real;
        require constraint { deltaV >= 150.0 }
    }

    requirement <'REQ-PRO-002'> specificImpulseReq {
        doc /* Thruster specific impulse shall exceed 220 seconds
             * for hydrazine monopropellant system. */
        attribute specificImpulse : Real;
        require constraint { specificImpulse >= 220.0 }
    }

    /* ===== Structural Requirements ===== */

    requirement <'REQ-STR-001'> launchLoadReq {
        doc /* Primary structure shall withstand quasi-static
             * launch loads of 10g in axial direction. */
        attribute loadCapacity : Real;
        require constraint { loadCapacity >= 10.0 }
    }

    requirement <'REQ-STR-002'> thermalControlReq {
        doc /* Thermal control shall maintain all components
             * within -20 to +50 degrees Celsius range. */
        attribute minTemp : Real;
        attribute maxTemp : Real;
        require constraint { minTemp >= -20.0 }
        require constraint { maxTemp <= 50.0 }
    }

    /* ===== Reliability Requirements ===== */

    requirement <'REQ-THR-001'> deploymentReliabilityReq {
        doc /* Deployment mechanism reliability shall exceed
             * 0.999 for all single-shot deployments. */
        attribute reliability : Real;
        require constraint { reliability >= 0.999 }
    }
}
