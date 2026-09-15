A production system has been deliberately sabotaged with interconnected failures. The sabotage creates chicken-and-egg dependencies: the tools you would normally use to repair the system are themselves broken. Some damage is delivered through persistent mechanisms that re-apply on shell startup.

Multiple subsystems are affected, spanning core utility permissions, authentication, name resolution, and user management. Diagnose all issues, neutralize any sabotage persistence mechanisms, and restore the system to full operational status.

When complete, the following must all work:

- All core system utilities (`chmod`, `chown`, `useradd`) are executable and functional
- `getent passwd root` returns root's entry
- PAM authentication in `/etc/pam.d/common-auth` is correctly configured
- Name resolution via `/etc/nsswitch.conf` uses the correct backends and remains correct across new shell sessions
- No shell startup scripts contain active sabotage that would revert your fixes
- `/etc/adduser.conf` has a valid default shell (DSHELL) pointing to an existing binary
- `/etc/login.defs` has valid UID/GID allocation ranges (UID_MIN < UID_MAX, GID_MIN < GID_MAX)
- Creating a new user works end-to-end: `useradd -m -s /bin/bash testuser` succeeds and `getent passwd testuser` resolves the new user