An Ansible automation project at `/app/ansible-project/` is intended to provision a multi-component web application infrastructure. The project is currently non-functional — multiple interacting failures across configuration, inventory, templates, variable definitions, and missing components prevent any playbook from executing successfully.

`/app/ansible-project/REQUIREMENTS.md` describes the target deployment state. Make the project fully operational: both `ansible-playbook site.yml` and `ansible-playbook report.yml` must complete without errors when run from `/app/ansible-project/` and produce the correct system state described in the requirements.

All inventory hosts use `ansible_connection=local`.