A firmware update simulator at `/app/firmware_sim` processes SB2-format update files through a multi-stage security verification pipeline. The application source is at `/app/src/main.c`, format definitions at `/app/include/sb2_format.h`, and a pre-compiled vendor parser at `/app/lib/sb2_parser.o`. System documentation is at `/app/docs/architecture.md`.

The update parser contains a vulnerability that allows bypassing the security verification stages. Exploit this vulnerability to make the simulator accept a crafted update file and extract the device's DICE Unique Device Secret (UDS).

Deliverables:

- `/app/exploit.sb2` — A crafted SB2 update file that bypasses all verification stages and causes the simulator to accept the update
- `/app/dice_uds.hex` — The extracted DICE UDS as a 64-character lowercase hex string with no spaces, no newline, and no prefix