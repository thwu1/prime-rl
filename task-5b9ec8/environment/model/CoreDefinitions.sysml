package CoreDefinitions {
    private import ScalarValues::*;

    /* Abstract root definition for any modeled element with mass */
    abstract part def Component {
        attribute mass : Real;
        attribute powerConsumption : Real;
    }

    /* Physical component with thermal operating range */
    part def PhysicalComponent :> Component {
        attribute operatingTempMin : Real;
        attribute operatingTempMax : Real;
    }

    /* Electrical component adds voltage/current characteristics */
    part def ElectricalComponent :> PhysicalComponent {
        attribute voltage : Real;
        attribute current : Real;
    }

    /* Instrument is an electrical component with data output capability */
    part def Instrument :> ElectricalComponent {
        attribute dataRate : Real;
        port dataOut : DataPort;
    }

    /* Subsystem adds mass and power budget tracking */
    part def Subsystem :> PhysicalComponent {
        attribute massBudget : Real;
        attribute powerBudget : Real;
    }

    /* Port definitions for data and power interfaces */
    port def DataPort {
        attribute dataRate : Real;
    }

    port def PowerPort {
        attribute voltage : Real;
        attribute current : Real;
    }

    port def RFPort {
        attribute frequency : Real;
        attribute gain : Real;
    }

    /* Interface definitions */
    interface def DataLink {
        end source : DataPort;
        end sink : DataPort;
    }

    interface def PowerBus {
        end supply : PowerPort;
        end load : PowerPort;
    }

    /* Enumeration for component operational state */
    enum def ComponentStatus {
        enum active;
        enum standby;
        enum failed;
    }

    enum def VerdictKind {
        enum pass;
        enum fail;
        enum inconclusive;
    }
}
