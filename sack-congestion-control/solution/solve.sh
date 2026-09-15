#!/bin/bash

# Ensure all infrastructure files exist in /app/
cp /opt/starter/packet.py /app/packet.py
cp /opt/starter/emulator.py /app/emulator.py
cp /opt/starter/run_transfer.py /app/run_transfer.py

# Replace the GBN sender and receiver with the SR+SACK+CC implementations.
cp /solution/sender_fixed.py /app/sender.py
cp /solution/receiver_fixed.py /app/receiver.py
