
import json
import os
import subprocess
import pytest


def run_scheduler(cluster_state):
    """Write cluster state to JSON, run the scheduler, read output."""
    state_path = "/app/cluster_state.json"
    output_path = "/app/schedule_output.json"

    if os.path.exists(output_path):
        os.remove(output_path)

    with open(state_path, "w") as f:
        json.dump(cluster_state, f, indent=2)

    result = subprocess.run(
        ["python3", "/app/scheduler.py"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Scheduler failed with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    assert os.path.exists(output_path), "Scheduler did not produce schedule_output.json"
    with open(output_path) as f:
        return json.load(f)


# =============================================================================
# FAIR-SHARE TESTS
# =============================================================================


class TestFairShareBasicEqualWeights:
    """Two groups with equal weights sharing 8 GPU slots equally."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [
                {"agent_id": "a1", "gpu_slots": 4, "mem_mb": 8192},
                {"agent_id": "a2", "gpu_slots": 4, "mem_mb": 8192},
            ],
            "groups": [
                {
                    "group_id": "grp-a", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "grp-b", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                {
                    "task_id": f"task-a{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-a",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:00:{i:02d}Z",
                }
                for i in range(4)
            ] + [
                {
                    "task_id": f"task-b{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-b",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:01:{i:02d}Z",
                }
                for i in range(4)
            ],
        }
        self.output = run_scheduler(self.state)

    def test_all_tasks_allocated(self):
        allocated = set(self.output["to_allocate"].keys())
        expected = {f"task-a{i}" for i in range(4)} | {f"task-b{i}" for i in range(4)}
        assert allocated == expected

    def test_no_releases(self):
        assert self.output["to_release"] == []

    def test_group_offers_equal(self):
        offers = self.output["group_offers"]
        assert offers["grp-a"] == 4
        assert offers["grp-b"] == 4

    def test_placement_valid(self):
        """Every allocated task must be placed on an agent from the input."""
        valid_agents = {"a1", "a2"}
        for task_id, agent_id in self.output["to_allocate"].items():
            assert agent_id in valid_agents, f"{task_id} placed on unknown agent {agent_id}"


class TestFairShareWeightedMaxSlots:
    """Weighted allocation with max_slots cap."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [{"agent_id": "a1", "gpu_slots": 10, "mem_mb": 20480}],
            "groups": [
                {
                    "group_id": "capped", "weight": 1.0, "priority": None,
                    "max_slots": 3, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "uncapped", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                {
                    "task_id": f"task-c{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "capped",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:00:{i:02d}Z",
                }
                for i in range(5)
            ] + [
                {
                    "task_id": f"task-u{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "uncapped",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:01:{i:02d}Z",
                }
                for i in range(8)
            ],
        }
        self.output = run_scheduler(self.state)

    def test_capped_group_offer(self):
        offers = self.output["group_offers"]
        assert offers["capped"] == 3
        assert offers["uncapped"] == 7

    def test_capped_group_tasks(self):
        allocated = set(self.output["to_allocate"].keys())
        capped_tasks = [t for t in allocated if t.startswith("task-c")]
        assert len(capped_tasks) == 3
        uncapped_tasks = [t for t in allocated if t.startswith("task-u")]
        assert len(uncapped_tasks) == 7


class TestFairShareMultiResource:
    """Memory constraints limit actual placements below the GPU-based offer."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [{"agent_id": "a1", "gpu_slots": 4, "mem_mb": 4096}],
            "groups": [
                {
                    "group_id": "grp-mem", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
            ],
            "tasks": [
                {
                    "task_id": f"task-m{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-mem",
                    "gpu_slots": 1, "mem_mb": 2048, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:00:{i:02d}Z",
                }
                for i in range(4)
            ],
        }
        self.output = run_scheduler(self.state)

    def test_gpu_offer_full(self):
        """GPU-based offer should be 4 (all demand met)."""
        assert self.output["group_offers"]["grp-mem"] == 4

    def test_memory_constrains_placement(self):
        """Only 2 tasks fit due to 4096MB / 2048MB per task."""
        allocated = self.output["to_allocate"]
        assert len(allocated) == 2

    def test_first_tasks_allocated(self):
        """Tasks with lowest position should be allocated first."""
        allocated = set(self.output["to_allocate"].keys())
        assert "task-m0" in allocated
        assert "task-m1" in allocated

    def test_agent_not_oversubscribed(self):
        """Agent's memory must not be oversubscribed."""
        a1_tasks = [
            tid for tid, aid in self.output["to_allocate"].items() if aid == "a1"
        ]
        # Each task uses 2048 MB, agent has 4096 MB
        assert len(a1_tasks) <= 2


class TestFairShareGangSuccess:
    """Gang group with enough capacity — all tasks allocated together."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [{"agent_id": "a1", "gpu_slots": 4, "mem_mb": 8192}],
            "groups": [
                {
                    "group_id": "gang-grp", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": True,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
            ],
            "tasks": [
                {
                    "task_id": "task-g0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "gang-grp",
                    "gpu_slots": 2, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:00:00Z",
                },
                {
                    "task_id": "task-g1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "gang-grp",
                    "gpu_slots": 2, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:00:01Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_all_gang_tasks_allocated(self):
        allocated = set(self.output["to_allocate"].keys())
        assert allocated == {"task-g0", "task-g1"}

    def test_gang_offer(self):
        assert self.output["group_offers"]["gang-grp"] == 4


class TestFairShareGangFailure:
    """Gang group can't fit all tasks — disabled and slots redistributed."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [{"agent_id": "a1", "gpu_slots": 6, "mem_mb": 12288}],
            "groups": [
                {
                    "group_id": "gang-grp", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": True,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
                {
                    "group_id": "normal", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
            ],
            "tasks": [
                # Gang group: 3 tasks of 2 GPU each = 6 total, but fair share
                # only gives it 3, which can't fit all 3 tasks together
                {
                    "task_id": f"task-gang{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "gang-grp",
                    "gpu_slots": 2, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:01:{i:02d}Z",
                }
                for i in range(3)
            ] + [
                {
                    "task_id": f"task-n{i}", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "normal",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:00:{i:02d}Z",
                }
                for i in range(6)
            ],
        }
        self.output = run_scheduler(self.state)

    def test_gang_group_disabled(self):
        """Gang group can't schedule all 3 tasks (need 6, got 3). Offer = 0."""
        assert self.output["group_offers"]["gang-grp"] == 0

    def test_no_gang_tasks_allocated(self):
        allocated = set(self.output["to_allocate"].keys())
        gang_tasks = [t for t in allocated if t.startswith("task-gang")]
        assert len(gang_tasks) == 0

    def test_normal_group_gets_redistributed_slots(self):
        """Normal group absorbs gang's reclaimed slots."""
        offers = self.output["group_offers"]
        assert offers["normal"] == 6

    def test_normal_tasks_allocated(self):
        allocated = set(self.output["to_allocate"].keys())
        normal_tasks = [t for t in allocated if t.startswith("task-n")]
        assert len(normal_tasks) == 6


class TestFairShareAntiAffinity:
    """Anti-affinity constraint forces groups onto different agents."""

    def setup_method(self):
        # grp-x and grp-y have anti-affinity in the DB
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [
                {"agent_id": "a1", "gpu_slots": 2, "mem_mb": 4096},
                {"agent_id": "a2", "gpu_slots": 2, "mem_mb": 4096},
            ],
            "groups": [
                {
                    "group_id": "grp-x", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "grp-y", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                {
                    "task_id": "task-x0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-x",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:00:00Z",
                },
                {
                    "task_id": "task-x1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-x",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:00:01Z",
                },
                {
                    "task_id": "task-y0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-y",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:01:00Z",
                },
                {
                    "task_id": "task-y1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-y",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:01:01Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_all_tasks_allocated(self):
        assert len(self.output["to_allocate"]) == 4

    def test_anti_affinity_respected(self):
        """grp-x and grp-y tasks must be on different agents."""
        alloc = self.output["to_allocate"]
        x_agents = {alloc[f"task-x{i}"] for i in range(2)}
        y_agents = {alloc[f"task-y{i}"] for i in range(2)}
        # No agent should appear in both sets
        assert x_agents.isdisjoint(y_agents), (
            f"Anti-affinity violated: grp-x on {x_agents}, grp-y on {y_agents}"
        )


class TestFairShareRelease:
    """Over-allocated group releases preemptible tasks to meet fair share."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [{"agent_id": "a1", "gpu_slots": 4, "mem_mb": 8192}],
            "groups": [
                {
                    "group_id": "grp-hog", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "grp-starved", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                # grp-hog has 4 running preemptible tasks (1 GPU each)
                {
                    "task_id": f"task-hog{i}",
                    "allocation_id": f"alloc-hog{i}",
                    "allocated_agent_id": "a1",
                    "group_id": "grp-hog",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": i,
                    "submitted_time": f"2024-01-01T00:00:{i:02d}Z",
                }
                for i in range(4)
            ] + [
                # grp-starved has 2 pending tasks
                {
                    "task_id": "task-starved0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-starved",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:01:00Z",
                },
                {
                    "task_id": "task-starved1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-starved",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:01:01Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_hog_releases_tasks(self):
        """grp-hog has 4 active but should have 2. Must release 2."""
        released = self.output["to_release"]
        assert len(released) == 2
        for alloc_id in released:
            assert alloc_id.startswith("alloc-hog")

    def test_starved_gets_allocated(self):
        allocated = set(self.output["to_allocate"].keys())
        assert "task-starved0" in allocated
        assert "task-starved1" in allocated

    def test_group_offers(self):
        offers = self.output["group_offers"]
        assert offers["grp-hog"] == 2
        assert offers["grp-starved"] == 2


# =============================================================================
# PRIORITY TESTS
# =============================================================================


class TestPriorityPreemption:
    """Higher priority pending task preempts lower priority running tasks."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "priority",
            "preemption_enabled": True,
            "agents": [{"agent_id": "a1", "gpu_slots": 4, "mem_mb": 8192}],
            "groups": [
                {
                    "group_id": "grp-hi", "weight": 1.0, "priority": 10,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "grp-lo", "weight": 1.0, "priority": 50,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                # High priority: pending, needs 3 GPU
                {
                    "task_id": "task-hi1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-hi",
                    "gpu_slots": 3, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:02:00Z",
                },
                # Low priority: 2 running tasks using all 4 GPU
                {
                    "task_id": "task-lo1", "allocation_id": "alloc-lo1",
                    "allocated_agent_id": "a1", "group_id": "grp-lo",
                    "gpu_slots": 2, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:01:00Z",
                },
                {
                    "task_id": "task-lo2", "allocation_id": "alloc-lo2",
                    "allocated_agent_id": "a1", "group_id": "grp-lo",
                    "gpu_slots": 2, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:01:01Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_preempts_low_priority(self):
        released = set(self.output["to_release"])
        assert len(released) == 2
        assert "alloc-lo1" in released
        assert "alloc-lo2" in released

    def test_high_priority_allocated(self):
        assert "task-hi1" in self.output["to_allocate"]


class TestPriorityBackfilling:
    """Lower priority preemptible tasks backfill unused slots."""

    def setup_method(self):
        self.state = {
            "scheduler_type": "priority",
            "preemption_enabled": True,
            "agents": [{"agent_id": "a1", "gpu_slots": 8, "mem_mb": 16384}],
            "groups": [
                {
                    "group_id": "grp-hi", "weight": 1.0, "priority": 10,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "grp-mid", "weight": 1.0, "priority": 30,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
                {
                    "group_id": "grp-lo", "weight": 1.0, "priority": 50,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:02:00Z",
                },
            ],
            "tasks": [
                # High: 6 GPU, non-preemptible
                {
                    "task_id": "task-hi1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-hi",
                    "gpu_slots": 6, "mem_mb": 1024, "preemptible": False,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:00:00Z",
                },
                # Mid: 4 GPU — can't fit in remaining 2
                {
                    "task_id": "task-mid1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-mid",
                    "gpu_slots": 4, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:01:00Z",
                },
                # Low: 1 GPU, preemptible — should backfill
                {
                    "task_id": "task-lo1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "grp-lo",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:02:00Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_high_priority_scheduled(self):
        assert "task-hi1" in self.output["to_allocate"]

    def test_mid_priority_not_scheduled(self):
        assert "task-mid1" not in self.output["to_allocate"]

    def test_low_priority_backfilled(self):
        """Low priority preemptible task backfills remaining slot."""
        assert "task-lo1" in self.output["to_allocate"]

    def test_no_preemptions(self):
        assert self.output["to_release"] == []


class TestGangAntiAffinityComplex:
    """Gang group + anti-affinity: gang tasks co-locate, other group on different agent."""

    def setup_method(self):
        # gang-a and other-b have anti-affinity in the DB
        self.state = {
            "scheduler_type": "fair_share",
            "agents": [
                {"agent_id": "a1", "gpu_slots": 2, "mem_mb": 4096},
                {"agent_id": "a2", "gpu_slots": 2, "mem_mb": 4096},
            ],
            "groups": [
                {
                    "group_id": "gang-a", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": True,
                    "registered_time": "2024-01-01T00:00:00Z",
                },
                {
                    "group_id": "other-b", "weight": 1.0, "priority": None,
                    "max_slots": None, "gang": False,
                    "registered_time": "2024-01-01T00:01:00Z",
                },
            ],
            "tasks": [
                # Gang group: 2 tasks, 1 GPU each
                {
                    "task_id": "task-ga0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "gang-a",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:00:00Z",
                },
                {
                    "task_id": "task-ga1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "gang-a",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:00:01Z",
                },
                # Other group: 2 tasks, 1 GPU each
                {
                    "task_id": "task-ob0", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "other-b",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 0,
                    "submitted_time": "2024-01-01T00:01:00Z",
                },
                {
                    "task_id": "task-ob1", "allocation_id": None,
                    "allocated_agent_id": None, "group_id": "other-b",
                    "gpu_slots": 1, "mem_mb": 1024, "preemptible": True,
                    "position": 1,
                    "submitted_time": "2024-01-01T00:01:01Z",
                },
            ],
        }
        self.output = run_scheduler(self.state)

    def test_all_tasks_allocated(self):
        assert len(self.output["to_allocate"]) == 4

    def test_gang_tasks_same_agent(self):
        """Gang tasks must be on the same agent (all-or-nothing placement)."""
        alloc = self.output["to_allocate"]
        ga_agents = {alloc["task-ga0"], alloc["task-ga1"]}
        assert len(ga_agents) == 1, f"Gang tasks on different agents: {ga_agents}"

    def test_anti_affinity_between_groups(self):
        """gang-a and other-b must not share any agent."""
        alloc = self.output["to_allocate"]
        ga_agents = {alloc["task-ga0"], alloc["task-ga1"]}
        ob_agents = {alloc["task-ob0"], alloc["task-ob1"]}
        assert ga_agents.isdisjoint(ob_agents), (
            f"Anti-affinity violated: gang-a on {ga_agents}, other-b on {ob_agents}"
        )

    def test_group_offers(self):
        offers = self.output["group_offers"]
        assert offers["gang-a"] == 2
        assert offers["other-b"] == 2
