"""Sandboxed execution of check programs."""
import multiprocessing


def check_correctness(problem, completion, timeout=5.0):
    """Execute a prediction against a problem's test suite in a sandboxed subprocess."""
    manager = multiprocessing.Manager()
    result = manager.list()

    check_program = (
        problem['prompt']
        + '\n'
        + completion
        + problem['test']
        + '\n'
        + f"check({problem['entry_point']})"
    )

    def worker(prog, res):
        try:
            exec_globals = {}
            exec(prog, exec_globals)
            res.append("passed")
        except Exception as e:
            res.append(f"failed: {type(e).__name__}: {e}")

    p = multiprocessing.Process(target=worker, args=(check_program, result))
    p.start()
    p.join(timeout=timeout + 1)

    if p.is_alive():
        p.kill()
        p.join()

    if not result:
        result.append("timed out")

    return {
        "task_id": problem["task_id"],
        "passed": result[0] == "passed",
        "result": result[0],
    }
