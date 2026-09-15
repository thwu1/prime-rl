#!/bin/bash
set -e

# Create groups
groupadd -f admins
groupadd -f developers
groupadd -f restricted
groupadd -f svcaccounts
groupadd -f wheel

# Create users with specific group memberships
useradd -m -G admins,wheel -s /bin/bash admin1
useradd -m -G developers -s /bin/bash dev1
useradd -m -G restricted -s /bin/bash restricted1
useradd -m -G svcaccounts -s /usr/sbin/nologin svcaccount

# Set passwords
echo 'admin1:Admin1Pass' | chpasswd
echo 'dev1:Dev1Pass' | chpasswd
echo 'restricted1:Restr1Pass' | chpasswd
echo 'svcaccount:SvcAcct1Pass' | chpasswd

# Create faillock directory
mkdir -p /var/run/faillock
