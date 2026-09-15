#!/usr/bin/env python3
"""Generate CPU affinity optimization task data: sysfs topology + ftrace trace."""
import json
import os
import random

random.seed(42)

TASKS = {
    "Input":    {"pid": 1004, "base_runtime": 300},
    "GameLoop": {"pid": 1000, "base_runtime": 1500},
    "Physics":  {"pid": 1001, "base_runtime": 4000},
    "Render":   {"pid": 1002, "base_runtime": 6000},
    "Audio":    {"pid": 1003, "base_runtime": 2000},
    "AI":       {"pid": 1005, "base_runtime": 5000},
    "NetSend":  {"pid": 1006, "base_runtime": 500},
    "PostProc": {"pid": 1007, "base_runtime": 2500},
    "AIDecide": {"pid": 1008, "base_runtime": 1000},
    "NetRecv":  {"pid": 1009, "base_runtime": 800},
    "NetProc":  {"pid": 1010, "base_runtime": 1200},
    "GC":       {"pid": 1011, "base_runtime": 3000},
}

CPUS = {}
for i in range(4):
    CPUS[i] = {"capacity": 1024, "power_mw": 5000, "freq_khz": 2400000,
               "core_id": i, "pkg_id": 0, "cache_group": "0-3"}
for i in range(4, 8):
    CPUS[i] = {"capacity": 717, "power_mw": 3000, "freq_khz": 1800000,
               "core_id": i - 4, "pkg_id": 0, "cache_group": "4-7"}
for i in range(8, 12):
    CPUS[i] = {"capacity": 410, "power_mw": 1500, "freq_khz": 1200000,
               "core_id": i - 8, "pkg_id": 0, "cache_group": "8-11"}

CURRENT_AFFINITY = {
    "Render": "0-3", "AI": "0-3",
    "Physics": "4-7", "GC": "4-7", "PostProc": "4-7", "Audio": "4-7",
    "GameLoop": "8-11", "Input": "8-11", "AIDecide": "8-11",
    "NetRecv": "8-11", "NetSend": "8-11", "NetProc": "8-11",
}

TASK_CPUS = {
    "Render": 0, "AI": 1,
    "Physics": 4, "GC": 5, "PostProc": 6, "Audio": 7,
    "GameLoop": 8, "Input": 9, "AIDecide": 10, "NetRecv": 11,
    "NetSend": 8, "NetProc": 9,
}

NUM_FRAMES = 20
FRAME_PERIOD_US = 16667


def jitter():
    return random.randint(-50, 50)


def actual_runtime(task_name):
    base = TASKS[task_name]["base_runtime"] + jitter()
    cap = CPUS[TASK_CPUS[task_name]]["capacity"]
    return round(base * 1024 / cap)


def _w(base, rel, content):
    path = os.path.join(base, rel)
    with open(path, "w") as f:
        f.write(content + "\n")


def gen_sysfs():
    base = "/app/data/sysfs"
    for cpu_id, info in CPUS.items():
        d = os.path.join(base, "cpu{}".format(cpu_id))
        for subdir in ["topology", "cpufreq", "power", "cache/index2"]:
            os.makedirs(os.path.join(d, subdir), exist_ok=True)
        _w(d, "topology/core_id", str(info["core_id"]))
        _w(d, "topology/physical_package_id", str(info["pkg_id"]))
        _w(d, "cpu_capacity", str(info["capacity"]))
        _w(d, "online", "1")
        _w(d, "cpufreq/scaling_max_freq", str(info["freq_khz"]))
        _w(d, "power/active_power_mw", str(info["power_mw"]))
        _w(d, "cache/index2/shared_cpu_list", info["cache_group"])


def switch_evt(ts_us, cpu, prev_comm, prev_pid, prev_state, next_comm, next_pid):
    return (ts_us, "switch", cpu, prev_comm, prev_pid, prev_state, next_comm, next_pid)


def wakeup_evt(ts_us, cpu, waker_comm, waker_pid, wakee_comm, wakee_pid, target_cpu):
    return (ts_us, "wakeup", cpu, waker_comm, waker_pid, wakee_comm, wakee_pid, target_cpu)


def gen_ftrace():
    events = []

    for frame in range(NUM_FRAMES):
        base_us = 1000000000 + frame * FRAME_PERIOD_US
        t = base_us

        # --- Input (timer-triggered, no real waker) ---
        cpu = TASK_CPUS["Input"]
        pid = TASKS["Input"]["pid"]
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "Input", pid))
        rt = actual_runtime("Input")
        t_end = t + rt
        events.append(wakeup_evt(t_end - 5, cpu, "Input", pid,
                                 "GameLoop", TASKS["GameLoop"]["pid"], TASK_CPUS["GameLoop"]))
        events.append(switch_evt(t_end, cpu, "Input", pid, "S", "swapper/{}".format(cpu), 0))

        # --- GameLoop ---
        cpu = TASK_CPUS["GameLoop"]
        pid = TASKS["GameLoop"]["pid"]
        t = t_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "GameLoop", pid))
        rt = actual_runtime("GameLoop")
        t_gl_end = t + rt
        for wakee in [("Physics", 20), ("AI", 15), ("Audio", 10), ("NetSend", 5)]:
            events.append(wakeup_evt(t_gl_end - wakee[1], cpu, "GameLoop", pid,
                                     wakee[0], TASKS[wakee[0]]["pid"], TASK_CPUS[wakee[0]]))
        events.append(switch_evt(t_gl_end, cpu, "GameLoop", pid, "S", "swapper/{}".format(cpu), 0))

        # --- Physics (parallel) ---
        cpu = TASK_CPUS["Physics"]
        pid = TASKS["Physics"]["pid"]
        t = t_gl_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "Physics", pid))
        rt = actual_runtime("Physics")
        t_phys_end = t + rt
        events.append(wakeup_evt(t_phys_end - 5, cpu, "Physics", pid,
                                 "Render", TASKS["Render"]["pid"], TASK_CPUS["Render"]))
        events.append(switch_evt(t_phys_end, cpu, "Physics", pid, "S", "swapper/{}".format(cpu), 0))

        # --- AI (parallel) ---
        cpu = TASK_CPUS["AI"]
        pid = TASKS["AI"]["pid"]
        t = t_gl_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "AI", pid))
        rt = actual_runtime("AI")
        t_ai_end = t + rt
        events.append(wakeup_evt(t_ai_end - 5, cpu, "AI", pid,
                                 "AIDecide", TASKS["AIDecide"]["pid"], TASK_CPUS["AIDecide"]))
        events.append(switch_evt(t_ai_end, cpu, "AI", pid, "S", "swapper/{}".format(cpu), 0))

        # --- Audio (parallel) ---
        cpu = TASK_CPUS["Audio"]
        pid = TASKS["Audio"]["pid"]
        t = t_gl_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "Audio", pid))
        rt = actual_runtime("Audio")
        events.append(switch_evt(t + rt, cpu, "Audio", pid, "S", "swapper/{}".format(cpu), 0))

        # --- NetSend (parallel, shares CPU with GameLoop) ---
        cpu = TASK_CPUS["NetSend"]
        pid = TASKS["NetSend"]["pid"]
        t = t_gl_end + 15
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "NetSend", pid))
        rt = actual_runtime("NetSend")
        events.append(switch_evt(t + rt, cpu, "NetSend", pid, "S", "swapper/{}".format(cpu), 0))

        # --- Render (after Physics) ---
        cpu = TASK_CPUS["Render"]
        pid = TASKS["Render"]["pid"]
        t = t_phys_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "Render", pid))
        rt = actual_runtime("Render")
        t_render_end = t + rt
        events.append(wakeup_evt(t_render_end - 5, cpu, "Render", pid,
                                 "PostProc", TASKS["PostProc"]["pid"], TASK_CPUS["PostProc"]))
        events.append(switch_evt(t_render_end, cpu, "Render", pid, "S", "swapper/{}".format(cpu), 0))

        # --- PostProc (after Render) ---
        cpu = TASK_CPUS["PostProc"]
        pid = TASKS["PostProc"]["pid"]
        t = t_render_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "PostProc", pid))
        rt = actual_runtime("PostProc")
        events.append(switch_evt(t + rt, cpu, "PostProc", pid, "S", "swapper/{}".format(cpu), 0))

        # --- AIDecide (after AI) ---
        cpu = TASK_CPUS["AIDecide"]
        pid = TASKS["AIDecide"]["pid"]
        t = t_ai_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "AIDecide", pid))
        rt = actual_runtime("AIDecide")
        events.append(switch_evt(t + rt, cpu, "AIDecide", pid, "S", "swapper/{}".format(cpu), 0))

        # --- NetRecv (timer-triggered, independent) ---
        cpu = TASK_CPUS["NetRecv"]
        pid = TASKS["NetRecv"]["pid"]
        t = base_us + 5000 + jitter()
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "NetRecv", pid))
        rt = actual_runtime("NetRecv")
        t_nr_end = t + rt
        events.append(wakeup_evt(t_nr_end - 5, cpu, "NetRecv", pid,
                                 "NetProc", TASKS["NetProc"]["pid"], TASK_CPUS["NetProc"]))
        events.append(switch_evt(t_nr_end, cpu, "NetRecv", pid, "S", "swapper/{}".format(cpu), 0))

        # --- NetProc (after NetRecv) ---
        cpu = TASK_CPUS["NetProc"]
        pid = TASKS["NetProc"]["pid"]
        t = t_nr_end + 10
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "NetProc", pid))
        rt = actual_runtime("NetProc")
        events.append(switch_evt(t + rt, cpu, "NetProc", pid, "S", "swapper/{}".format(cpu), 0))

        # --- GC (timer-triggered, independent) ---
        cpu = TASK_CPUS["GC"]
        pid = TASKS["GC"]["pid"]
        t = base_us + 10000 + jitter()
        events.append(switch_evt(t, cpu, "swapper/{}".format(cpu), 0, "R", "GC", pid))
        rt = actual_runtime("GC")
        events.append(switch_evt(t + rt, cpu, "GC", pid, "S", "swapper/{}".format(cpu), 0))

    events.sort(key=lambda e: e[0])
    return format_ftrace(events)


def format_ftrace(events):
    lines = [
        "# tracer: nop",
        "#",
        "# entries-in-buffer/entries-written: {0}/{0}   #P:12".format(len(events)),
        "#",
        "#                                _-----=> irqs-off/BH-disabled",
        "#                               / _----=> need-resched",
        "#                              | / _---=> hardirq/softirq",
        "#                             || / _--=> preempt-depth",
        "#                             ||| / _-=> migrate-disable",
        "#                            |||| /     delay",
        "#           TASK-PID     CPU#  |||||  TIMESTAMP  FUNCTION",
        "#              | |         |   |||||     |         |",
    ]
    for evt in events:
        ts_s = evt[0] / 1e6
        if evt[1] == "switch":
            _, _, cpu, prev_comm, prev_pid, prev_state, next_comm, next_pid = evt
            task_str = "{}-{}".format(prev_comm, prev_pid)
            fields = ("prev_comm={} prev_pid={} prev_prio=120 prev_state={} "
                      "==> next_comm={} next_pid={} next_prio=120").format(
                prev_comm, prev_pid, prev_state, next_comm, next_pid)
            lines.append(" {:>16s} [{:03d}] d..1. {:>13.6f}: sched_switch: {}".format(
                task_str, cpu, ts_s, fields))
        elif evt[1] == "wakeup":
            _, _, cpu, waker_comm, waker_pid, wakee_comm, wakee_pid, target_cpu = evt
            task_str = "{}-{}".format(waker_comm, waker_pid)
            fields = "comm={} pid={} prio=120 target_cpu={:03d}".format(
                wakee_comm, wakee_pid, target_cpu)
            lines.append(" {:>16s} [{:03d}] d..1. {:>13.6f}: sched_wakeup: {}".format(
                task_str, cpu, ts_s, fields))
    return "\n".join(lines) + "\n"


def main():
    os.makedirs("/app/data", exist_ok=True)
    gen_sysfs()

    trace = gen_ftrace()
    with open("/app/data/trace.txt", "w") as f:
        f.write(trace)

    with open("/app/data/affinity.json", "w") as f:
        json.dump({
            "assignments": CURRENT_AFFINITY,
            "description": "Tasks assigned to CPU clusters by descending average runtime"
        }, f, indent=2)

    with open("/app/data/requirements.json", "w") as f:
        json.dump({
            "target_frame_time_us": 16667,
            "energy_budget_joules": 2.70,
            "num_frames": 20,
        }, f, indent=2)

    print("Generated task data: sysfs topology (12 CPUs), ftrace trace ({} frames), affinity config".format(NUM_FRAMES))


if __name__ == "__main__":
    main()
