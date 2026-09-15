#!/bin/bash
# Telemetry subsystem query handler
case "$1" in
    power)
        echo "SUBSYS:POWER STATUS:NOMINAL VOLTAGE:28.3V CURRENT:4.2A TEMP:45.2C"
        ;;
    thermal)
        echo "SUBSYS:THERMAL STATUS:NOMINAL PANEL_TEMP:22.4C CORE_TEMP:67.1C COOLANT:OK"
        ;;
    comms)
        echo "SUBSYS:COMMS STATUS:ACTIVE FREQ:2.4GHz SIGNAL:-42dBm LATENCY:240ms"
        ;;
    attitude)
        echo "SUBSYS:ATTITUDE STATUS:NOMINAL ROLL:0.02 PITCH:-0.01 YAW:0.03"
        ;;
    navigation)
        echo "SUBSYS:NAV STATUS:TRACKING SAT_COUNT:14 ORBIT:LEO ALT:408.2km"
        ;;
    *)
        echo "ERROR: Unknown subsystem '$1'. Available: power, thermal, comms, attitude, navigation"
        ;;
esac
