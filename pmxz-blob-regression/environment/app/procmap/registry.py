
"""Process registry for managing serialized process maps of HPC jobs.

Provides storage and retrieval of process maps, with automatic
serialization and validation on read-back.
"""

import os

from procmap.generator import generate_procmap, parse_procmap
from procmap.serialize import serialize_procmap, deserialize_procmap


class ProcessRegistry:
    """Registry for storing and retrieving process maps of HPC jobs."""

    def __init__(self, storage_dir="/tmp/procmap_registry"):
        """Initialize the registry with a storage directory.

        Args:
            storage_dir: Directory for storing serialized process maps.
                        Created if it does not exist.
        """
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def register_job(self, job_id, nprocs, nnodes):
        """Register a job by generating and storing its process map.

        Args:
            job_id: Unique job identifier (used as filename base)
            nprocs: Total number of processes
            nnodes: Number of compute nodes

        Returns:
            The generated process map string
        """
        procmap = generate_procmap(nprocs, nnodes)
        serialized = serialize_procmap(procmap)

        filepath = os.path.join(self.storage_dir, f"job_{job_id}.pmx")
        with open(filepath, 'wb') as f:
            f.write(serialized)

        return procmap

    def get_job_procmap(self, job_id):
        """Retrieve and deserialize a stored process map.

        Args:
            job_id: Job identifier

        Returns:
            Process map string

        Raises:
            FileNotFoundError: If no map is stored for this job
        """
        filepath = os.path.join(self.storage_dir, f"job_{job_id}.pmx")
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"No process map found for job {job_id}"
            )

        with open(filepath, 'rb') as f:
            data = f.read()

        return deserialize_procmap(data)

    def verify_job(self, job_id, nprocs, nnodes):
        """Verify a stored process map matches expected parameters.

        Re-reads the serialized data, deserializes it, and checks:
        - Total process count equals nprocs
        - Node count equals nnodes
        - All ranks 0..nprocs-1 are present exactly once

        Args:
            job_id: Job identifier
            nprocs: Expected number of processes
            nnodes: Expected number of nodes

        Returns:
            True if verification passes

        Raises:
            ValueError: If verification fails
            FileNotFoundError: If the job is not registered
        """
        procmap_str = self.get_job_procmap(job_id)
        procmap = parse_procmap(procmap_str)

        actual_nnodes = len(procmap)
        all_ranks = []
        for ranks in procmap.values():
            all_ranks.extend(ranks)

        actual_nprocs = len(all_ranks)

        if actual_nnodes != nnodes:
            raise ValueError(
                f"Node count mismatch: expected {nnodes}, "
                f"got {actual_nnodes}"
            )

        if actual_nprocs != nprocs:
            raise ValueError(
                f"Process count mismatch: expected {nprocs}, "
                f"got {actual_nprocs}"
            )

        expected_ranks = set(range(nprocs))
        actual_rank_set = set(all_ranks)

        if actual_rank_set != expected_ranks:
            missing = expected_ranks - actual_rank_set
            extra = actual_rank_set - expected_ranks
            raise ValueError(
                f"Rank mismatch: "
                f"missing={sorted(list(missing))[:10]}, "
                f"extra={sorted(list(extra))[:10]}"
            )

        return True

    def list_jobs(self):
        """List all registered job IDs.

        Returns:
            List of job ID strings
        """
        jobs = []
        for fname in os.listdir(self.storage_dir):
            if fname.startswith("job_") and fname.endswith(".pmx"):
                job_id = fname[4:-4]  # strip "job_" prefix and ".pmx" suffix
                jobs.append(job_id)
        return sorted(jobs)

    def remove_job(self, job_id):
        """Remove a stored process map.

        Args:
            job_id: Job identifier

        Raises:
            FileNotFoundError: If the job is not registered
        """
        filepath = os.path.join(self.storage_dir, f"job_{job_id}.pmx")
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"No process map found for job {job_id}"
            )
        os.remove(filepath)
