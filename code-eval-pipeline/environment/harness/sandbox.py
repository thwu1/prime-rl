"""Sandboxed code execution with timeout enforcement."""
import multiprocessing


def _worker(prog, res):
    """Execute a check program and report result."""
    try:
        exec_globals = {}
        exec(prog, exec_globals)
        res.append("passed")
    except Exception as e:
        res.append(f"failed: {type(e).__name__}: {e}")


def assemble_and_run(problem, code, timeout=5):
    """Assemble check program from components and execute in sandbox.

    Concatenates prompt + code + test_code + check call,
    then runs in an isolated subprocess with timeout.
    """
    check_program = (
        problem["prompt"]
        + "\n"
        + code
        + problem["test_code"]
        + "\n"
        + f"check({problem['entry_point']})"
    )
    return run_check(check_program, timeout)


def run_check(check_program, timeout=5):
    """Execute a check program in an isolated subprocess with timeout."""
    manager = multiprocessing.Manager()
    result = manager.list()

    p = multiprocessing.Process(target=_worker, args=(check_program, result))
    p.start()
    p.join(timeout=timeout)

    if p.is_alive():
        p.kill()
        p.join()

    if not result:
        return "timed out"
    return result[0]
