"""Main analyzer for benchmark evaluation."""
from loader import load_models, load_tasks, load_all_runs
from metrics import compute_resolved_rate, compute_sem, compute_pass_at_k
from contamination import count_contaminated_tasks


class Analyzer:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.models = load_models(data_dir)
        self.tasks = load_tasks(data_dir)

    def compute_leaderboard(self, start_date=None, end_date=None):
        """Compute the full leaderboard."""
        tasks = self.tasks
        task_ids = [t["id"] for t in tasks]

        rankings = []
        for model in self.models:
            runs = load_all_runs(self.data_dir, model["name"])

            resolved_rate = compute_resolved_rate(runs, task_ids)
            sem = compute_sem(runs, task_ids)
            pass_at_1 = compute_pass_at_k(runs, task_ids, 1)
            pass_at_3 = compute_pass_at_k(runs, task_ids, 3)
            pass_at_5 = compute_pass_at_k(runs, task_ids, 5)

            num_contaminated = count_contaminated_tasks(tasks, model["release_date"])

            rankings.append({
                "model": model["name"],
                "resolved_rate": round(resolved_rate, 5),
                "sem": round(sem, 5),
                "pass_at_1": round(pass_at_1, 5),
                "pass_at_3": round(pass_at_3, 5),
                "pass_at_5": round(pass_at_5, 5),
                "num_contaminated_tasks": num_contaminated,
                "contamination_fraction": round(
                    num_contaminated / len(task_ids), 5
                ) if task_ids else 0,
            })

        rankings.sort(key=lambda x: x["resolved_rate"], reverse=True)

        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        task_difficulty = self._compute_task_difficulty(task_ids)

        return {
            "time_window": {
                "start": start_date,
                "end": end_date,
            },
            "num_tasks": len(task_ids),
            "num_runs_per_model": 5,
            "rankings": rankings,
            "task_difficulty": task_difficulty,
        }

    def _compute_task_difficulty(self, task_ids):
        """Compute difficulty metrics for each task."""
        difficulties = []
        for tid in task_ids:
            solve_rates = []
            num_solved = 0
            for model in self.models:
                runs = load_all_runs(self.data_dir, model["name"])
                c = sum(1 for run in runs if run.get(tid, False))
                solve_rates.append(c / len(runs))
                if c > 0:
                    num_solved += 1

            difficulties.append({
                "task_id": tid,
                "mean_solve_rate": round(
                    sum(solve_rates) / len(solve_rates), 5
                ),
                "num_models_solved_at_least_once": num_solved,
            })

        difficulties.sort(key=lambda x: x["mean_solve_rate"])

        return difficulties
