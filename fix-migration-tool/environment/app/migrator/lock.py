"""File-based locking for preventing concurrent migration execution."""
import os
import time


class MigrationLock:
    """File-based lock to prevent concurrent migration runs."""

    def __init__(self, lock_path):
        self.lock_path = lock_path

    def acquire(self, timeout=10):
        """Acquire the migration lock. Cleans stale locks from dead processes."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            if os.path.exists(self.lock_path):
                if self._is_stale():
                    os.unlink(self.lock_path)
                else:
                    time.sleep(0.1)
                    continue

            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                time.sleep(0.1)

        raise TimeoutError(
            f"Could not acquire migration lock within {timeout}s. "
            f"Lock file: {self.lock_path}"
        )

    def release(self):
        """Release the migration lock."""
        try:
            os.unlink(self.lock_path)
        except FileNotFoundError:
            pass

    def _is_stale(self):
        """Check if the lock is held by a dead process."""
        try:
            with open(self.lock_path) as f:
                pid = f.read().strip()
            # Check if process is still running
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except Exception:
            return False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
