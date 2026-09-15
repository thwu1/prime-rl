package SubsystemDefinitions {
    private import CoreDefinitions::*;
    private import ScalarValues::*;

    /* ---- Payload Subsystem ---- */
    part def PayloadSubsystem :> Subsystem {
        doc /* The payload subsystem houses all
             * mission-critical sensing instruments
             * and data recording equipment. */
        part opticalImager : OpticalImager;
        part sarUnit : SARUnit;
        part dataRecorder : DataRecorder;
    }

    part def OpticalImager :> Instrument {
        /* Inherits: mass, powerConsumption (Component)
         *           operatingTempMin/Max (PhysicalComponent)
         *           voltage, current (ElectricalComponent)
         *           dataRate, dataOut (Instrument)
         * Adds: resolution, focalLength */
        attribute resolution : Real;
        attribute focalLength : Real;
    }

    part def SARUnit :> Instrument {
        doc /* Synthetic Aperture Radar unit for
             * all-weather imaging capability */
        attribute swathWidth : Real;
        attribute frequency : Real;
    }

    part def DataRecorder :> ElectricalComponent {
        /* NOT an Instrument — lacks dataRate and dataOut port */
        attribute storageCapacity : Real;
        port dataIn : DataPort;
    }

    /* ---- Power Subsystem ---- */
    part def PowerSubsystem :> Subsystem {
        part solarArray : SolarArray;
        part batteryPack : BatteryPack;
        part powerController : PowerController;
    }

    part def SolarArray :> ElectricalComponent {
        attribute panelArea : Real;
        attribute efficiency : Real;
        attribute powerOutput : Real;
        port powerOut : PowerPort;
    }

    part def BatteryPack :> ElectricalComponent {
        attribute capacity : Real;
        port powerIn : PowerPort;
        port powerOut : PowerPort;
    }

    part def PowerController :> ElectricalComponent {
        port busIn : PowerPort;
        port busOut : PowerPort;
    }

    /* ---- ADCS Subsystem ---- */
    part def ADCSSubsystem :> Subsystem {
        doc /* Attitude Determination and Control Subsystem
             * Provides 3-axis stabilization and pointing */
        part reactionWheelCluster : ReactionWheelCluster;
        part starTracker : StarTracker;
        part magnetorquer : Magnetorquer;
    }

    part def ReactionWheelCluster :> PhysicalComponent {
        /* Mechanical assembly — not an ElectricalComponent */
        attribute wheelCount : Integer;
        attribute maxTorque : Real;
        attribute maxMomentum : Real;
    }

    part def StarTracker :> ElectricalComponent {
        attribute fieldOfView : Real;
        attribute accuracy : Real;
    }

    part def Magnetorquer :> ElectricalComponent {
        attribute dipole : Real;
    }

    /* ---- Communications Subsystem ---- */
    part def CommSubsystem :> Subsystem {
        part sBandTransponder : SBandTransponder;
        part xBandTransmitter : XBandTransmitter;
        part highGainAntenna : HighGainAntenna;
    }

    part def SBandTransponder :> ElectricalComponent {
        attribute txPower : Real;
        port rfPort : RFPort;
    }

    part def XBandTransmitter :> Instrument {
        /* IS an Instrument — high-rate data transmitter with measurable throughput */
        attribute txPower : Real;
        port rfPort : RFPort;
    }

    part def HighGainAntenna :> PhysicalComponent {
        /* Passive antenna — not an ElectricalComponent */
        attribute diameter : Real;
        attribute gain : Real;
    }

    /* ---- Propulsion Subsystem ---- */
    part def PropulsionSubsystem :> Subsystem {
        part thrusterCluster : ThrusterCluster;
        part propellantTank : PropellantTank;
        part feedSystem : FeedSystem;
    }

    part def ThrusterCluster :> PhysicalComponent {
        attribute thrustLevel : Real;
        attribute specificImpulse : Real;
        attribute thrusterCount : Integer;
    }

    part def PropellantTank :> PhysicalComponent {
        attribute volume : Real;
        attribute maxPressure : Real;
    }

    part def FeedSystem :> PhysicalComponent {
        attribute nominalPressure : Real;
    }

    /* ---- Structure Subsystem ---- */
    part def StructureSubsystem :> Subsystem {
        part primaryBus : PrimaryBus;
        part deploymentMechanism : DeploymentMechanism;
        part thermalBlanket : ThermalBlanket;
    }

    part def PrimaryBus :> PhysicalComponent {
        attribute material : String;
        attribute loadCapacity : Real;
    }

    part def DeploymentMechanism :> PhysicalComponent {
        attribute reliability : Real;
    }

    part def ThermalBlanket :> PhysicalComponent {
        attribute minTemp : Real;
        attribute maxTemp : Real;
    }
}
