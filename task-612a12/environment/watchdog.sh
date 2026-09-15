#!/bin/bash
# Watchdog for the metrics collector daemon.
# Monitors collector process and restarts it if it dies or exceeds
# the virtual memory limit.

COLLECTOR=/app/collector
MAX_VMSZ_KB=1048576   # 1 GB virtual memory limit
CHECK_INTERVAL=10
LOG=/var/log/collector/watchdog.log

collector_pid=""

start_collector() {
    $COLLECTOR &
    collector_pid=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] watchdog: started collector (pid $collector_pid)" >> $LOG
}

check_memory() {
    if [ -f "/proc/$collector_pid/status" ]; then
        vmsz=$(grep VmSize /proc/$collector_pid/status 2>/dev/null | awk '{print $2}')
        if [ -n "$vmsz" ] && [ "$vmsz" -gt "$MAX_VMSZ_KB" ] 2>/dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] watchdog: collector (pid $collector_pid) exceeded virtual memory limit (${vmsz} kB > ${MAX_VMSZ_KB} kB), killing" >> $LOG
            kill -9 $collector_pid 2>/dev/null
            wait $collector_pid 2>/dev/null
            return 1
        fi
    fi
    return 0
}

start_collector

while true; do
    sleep $CHECK_INTERVAL

    if ! kill -0 $collector_pid 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] watchdog: collector (pid $collector_pid) exited, restarting" >> $LOG
        start_collector
    else
        if ! check_memory; then
            start_collector
        fi
    fi
done
