#!/bin/bash

# Install the PieceTable implementation
cp /solution/piece_table_impl.py /app/piece_table.py

# Copy pipeline script and Makefile
cp /solution/replay.py /app/replay.py
cp /solution/Makefile /app/Makefile

# Create the entry-point script
cat > /app/replay_journal.sh << 'SCRIPT'
#!/bin/bash
make -C /app all
SCRIPT
chmod +x /app/replay_journal.sh

# Run the pipeline
cd /app && bash /app/replay_journal.sh
