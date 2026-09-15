Implement a TCP server for an average-speed enforcement system on a road network. The server coordinates speed cameras and ticket dispatchers using a custom binary protocol.

The full protocol specification is at `/app/PROTOCOL.md`. Read it carefully before implementing.

Your server must:
- Be startable via `bash /app/run.sh` and listen on TCP port **9000**
- Support at least 150 simultaneous client connections
- Handle two client types over a binary protocol (no delimiters between messages):
  - **Cameras** identify themselves with road, mile position, and speed limit, then report license plate observations with timestamps
  - **Ticket dispatchers** identify themselves with the roads they serve, then receive speeding violation tickets
- Detect average speed violations between **any pair** of observations for the same car on the same road (not just adjacent cameras)
- Enforce the **one-ticket-per-car-per-day** rule across all roads, where a ticket spanning multiple days blocks ticketing on every spanned day
- **Queue tickets** for roads with no connected dispatcher and deliver them when a dispatcher connects
- Support periodic heartbeat messages at client-requested intervals
- Send an Error message and disconnect on any protocol violation (duplicate identity, plate before identification, duplicate heartbeat request, unknown message type)