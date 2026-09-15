package Functions {

    /* Top-level mission action */
    action def PerformMission {
        doc /* Top-level mission function decomposition for
             * the SentinelSat remote sensing satellite. */
    }

    /* Leaf-level action definitions */

    action def AcquireTarget {
        doc /* Determine and lock onto the next imaging target
             * based on mission planning schedule. */
    }

    action def CaptureOpticalImage {
        doc /* Perform optical image acquisition with the
             * multispectral imager instrument. */
    }

    action def CaptureSARImage {
        doc /* Perform SAR image acquisition in the
             * configured imaging mode (stripmap/spotlight). */
    }

    action def StoreData {
        doc /* Write acquired sensor data to the on-board
             * solid-state data recorder. */
    }

    action def DownlinkData {
        doc /* Transmit buffered science data to ground
             * station during communication window. */
    }

    action def PerformOrbitMaintenance {
        doc /* Execute station-keeping maneuvers to maintain
             * the nominal orbit parameters. */
    }

    action def PointSpacecraft {
        doc /* Slew and stabilize spacecraft attitude for
             * the commanded pointing direction. */
    }

    action def ManagePower {
        doc /* Control power distribution, battery charging,
             * and load shedding as needed. */
    }

    action def PerformCalibration {
        doc /* Execute periodic calibration sequences for
             * all on-board instruments and sensors. */
    }

    action def MonitorHealth {
        doc /* Continuous monitoring of spacecraft health
             * telemetry and anomaly detection. */
    }

    /* Mission action decomposition with sequencing */
    action performMission : PerformMission {
        action acquireTarget : AcquireTarget;
        then action pointSpacecraft : PointSpacecraft;
        then action captureOpticalImage : CaptureOpticalImage;
        then action captureSARImage : CaptureSARImage;
        then action storeData : StoreData;
        then action downlinkData : DownlinkData;
        action performOrbitMaintenance : PerformOrbitMaintenance;
        action managePower : ManagePower;
        action performCalibration : PerformCalibration;
        action monitorHealth : MonitorHealth;
    }
}
