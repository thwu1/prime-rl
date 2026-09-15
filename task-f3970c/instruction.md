`/app/resolve.py` resolves Discourse Docker container configurations by compositing YAML templates from `/app/templates/` with container definitions from `/app/containers/`. The bash launcher script at `/app/launcher` is the sole authoritative reference for correct resolution behavior. The resolver has multiple bugs producing incorrect output. Fix all bugs so the resolver matches the launcher's semantics.

Create `/app/analyze_deployment.py` — reads the manifest at `/app/deployment.json`, resolves all listed containers (using `--hostname testhost`), and outputs JSON to stdout with two keys:

`"audit"`: list of findings, each with `"type"` (string), `"severity"` (`"error"` or `"warning"`), `"containers"` (list of names), `"detail"` (string). Required detection types:

- `"port_conflict"`: multiple containers publishing the same host port on the same bind address
- `"bundled_plugin"`: hooks cloning plugins from the resolver's `BUNDLED_PLUGINS` list (warning severity)
- `"localhost_binding"`: a container binding ports to 127.0.0.1 while another container's `DISCOURSE_DB_HOST` or `DISCOURSE_REDIS_HOST` references it (error severity)

`"compose"`: valid docker-compose YAML string (version `"3.8"`), one service per container. Each service must have `image`, `container_name`, `hostname`, `mac_address`, `ports`, `expose`, `volumes`, `environment`, and `command` from the resolved config. Include `depends_on` when `DISCOURSE_DB_HOST` or `DISCOURSE_REDIS_HOST` matches another container's name in the deployment.

Resolver: `python3 /app/resolve.py <config> --base-dir /app --hostname testhost`

Analyzer: `python3 /app/analyze_deployment.py --base-dir /app`