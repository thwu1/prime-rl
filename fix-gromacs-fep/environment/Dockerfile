FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install GROMACS and python3-pip
RUN apt-get update && apt-get install -y gromacs python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy input files for system preparation
COPY methanol.gro /app/methanol.gro
COPY topol_initial.top /app/topol.top
COPY em.mdp /app/em.mdp

# Create simulation box (cubic, 1.0 nm buffer)
RUN gmx editconf -f /app/methanol.gro -o /app/box.gro -bt cubic -d 1.0 2>&1

# Solvate with SPC water (modifies topol.top in-place to add SOL count)
RUN gmx solvate -cp /app/box.gro -cs spc216.gro -o /app/solvated.gro -p /app/topol.top 2>&1

# Energy minimize to remove clashes
RUN gmx grompp -f /app/em.mdp -c /app/solvated.gro -p /app/topol.top -o /app/em.tpr -maxwarn 5 2>&1 && \
    gmx mdrun -deffnm /app/em -ntmpi 1 -ntomp 1 2>&1

# Keep minimized system as starting point; clean up intermediates
RUN mv /app/em.gro /app/system.gro && \
    rm -f /app/box.gro /app/solvated.gro /app/em.tpr /app/em.trr /app/em.edr /app/em.log /app/mdout.mdp /app/methanol.gro /app/em.mdp

# Copy the FEP template and run script (these contain bugs for the agent to fix)
COPY fep.mdp /app/fep.mdp
COPY run_fep.sh /app/run_fep.sh
RUN chmod +x /app/run_fep.sh
