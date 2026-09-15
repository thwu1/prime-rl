A multi-view video world-model inference service for robotic manipulation is deployed at `/app/`. Three interconnected subsystems need diagnosis and repair:

**Pipeline modules** (`/app/pipeline/`) implement rectified flow matching, VAE latent geometry, reference-frame conditioning, per-channel normalization, classifier-free guidance, and two-stage denoising. All modules contain subtle bugs that cause incorrect inference outputs. A research paper excerpt at `/app/paper_excerpt.md` describes the correct theoretical formulations. A validation harness at `/app/validate.py` checks each component against reference values at `/app/reference/expected.json`. The config at `/app/config.yaml` supplies the validation parameters.

**Orchestrator** (`/app/orchestrator.py`) has four stub functions for parsing `.wme` binary episode files, computing multi-view latent geometry alignment, planning autoregressive chunk schedules with adaptive denoising parameters, and building a SQLite inference plan database. The binary format spec is at `/app/spec.md`. The database schema is at `/app/schema.sql`. Episode files are at `/app/episodes/`.

**ZMQ plan server** (`/app/server.py`) serves inference plans from the plan database to remote clients over ZeroMQ. The server has protocol-level bugs that prevent clients using `zmq.REQ` sockets from receiving valid JSON responses.

Fix all pipeline bugs, implement the orchestrator, and repair the ZMQ server so that:
- `python3 /app/validate.py` reports all 13 checks passing
- `python3 /app/orchestrator.py` produces a correct plan database at `/app/output/plan.db`
- The ZMQ server correctly serves plan queries on the port specified via `--port`