#!/bin/bash
set -e

cd /app/registry
git init
git config user.email "admin@dn42.registry"
git config user.name "DN42 Registry Bot"

mkdir -p data/{mntner,person,aut-num,inetnum,inet6num,route,route6,dns}

# Stage 1: Initial valid registry
cp /tmp/stages/stage1/mntner/* data/mntner/
cp /tmp/stages/stage1/person/* data/person/
cp /tmp/stages/stage1/aut-num/* data/aut-num/
cp /tmp/stages/stage1/inetnum/* data/inetnum/
cp /tmp/stages/stage1/inet6num/* data/inet6num/
cp /tmp/stages/stage1/route/* data/route/
cp /tmp/stages/stage1/route6/* data/route6/
cp /tmp/stages/stage1/dns/* data/dns/
git add -A
GIT_AUTHOR_DATE="2024-06-01T10:00:00+00:00" GIT_COMMITTER_DATE="2024-06-01T10:00:00+00:00" \
  git commit -m "Initial registry import"

# Stage 2: Add new autonomous systems (introduces dangling person references)
cp /tmp/stages/stage2/aut-num/* data/aut-num/
git add -A
GIT_AUTHOR_DATE="2024-07-15T14:30:00+00:00" GIT_COMMITTER_DATE="2024-07-15T14:30:00+00:00" \
  git commit -m "Register new autonomous systems"

# Stage 3: Add external routes and update policies (introduces route violations)
cp /tmp/stages/stage3/route/* data/route/
cp /tmp/stages/stage3/route6/* data/route6/
git add -A
GIT_AUTHOR_DATE="2024-09-22T09:15:00+00:00" GIT_COMMITTER_DATE="2024-09-22T09:15:00+00:00" \
  git commit -m "Add external routes and update policies"

# Stage 4: Add DNS zones and network allocations (introduces more dangling refs)
cp /tmp/stages/stage4/dns/* data/dns/
cp /tmp/stages/stage4/inetnum/* data/inetnum/
git add -A
GIT_AUTHOR_DATE="2024-11-03T16:45:00+00:00" GIT_COMMITTER_DATE="2024-11-03T16:45:00+00:00" \
  git commit -m "Add DNS zones and network allocations"

echo "Registry setup complete: $(git log --oneline | wc -l) commits"
