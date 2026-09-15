#!/bin/bash

# Fix all architectural flaws and bugs in the Ansible project
python3 /solution/solve.py

cd /app
ansible-playbook site.yml
