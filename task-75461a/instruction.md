The file `/app/cluster_spec.yaml` defines an 8-node Flux HPC cluster topology with three resource groups, three named scheduling queues, a statically excluded node, and job management settings.

Write a valid Flux configuration file at `/app/flux_config/system.toml` that implements the configuration aspects of this specification. The Flux framework is pre-installed (`flux` available in PATH).

The configuration will be validated by launching an 8-broker Flux test instance (hostnames `test[0-7]`) with `/app/flux_config` as its configuration directory. All of the following must hold:

- All defined queues are functional and accept job submissions
- Jobs submitted to each queue are scheduled exclusively on nodes carrying the matching resource property
- The excluded node is never allocated to any job
- Jobs submitted without specifying a queue are routed to the default queue designated in the cluster spec
- Unsatisfiable resource requests (e.g., requesting more nodes than available in a queue's resource group) result in a scheduler exception
- Jobs whose requested duration exceeds a queue's policy limit are rejected at submission
- Job manager inactive-job housekeeping settings match the specification values