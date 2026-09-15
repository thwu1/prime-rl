"""
Transfer harness that runs a sender and receiver in separate threads,
mediating a complete reliable data transfer over a LossyChannel.
"""

import threading
import time



def transfer(sender_cls, receiver_cls, channel, data: bytes, config: dict,
             timeout: float = 120.0):
    """
    Execute a reliable transfer from sender to receiver.

    Parameters
    ----------
    sender_cls : type
        Class with ``__init__(channel, config)`` and ``send(data) -> stats``.
    receiver_cls : type
        Class with ``__init__(channel, config)`` and ``receive() -> bytes``.
    channel : LossyChannel
        The channel connecting sender and receiver.
    data : bytes
        Payload to transfer.
    config : dict
        Protocol configuration (mss, max_window, seq_bits, etc.).
    timeout : float
        Maximum wall-clock time for the transfer in seconds.

    Returns
    -------
    (received_data, sender_stats, elapsed_seconds)

    Raises
    ------
    RuntimeError
        On transfer failure, thread error, or timeout.
    """
    sender = sender_cls(channel, config)
    receiver = receiver_cls(channel, config)

    result = {'received': None, 'stats': None, 'errors': []}

    def run_sender():
        try:
            result['stats'] = sender.send(data)
        except Exception as e:
            result['errors'].append(('sender', str(e)))

    def run_receiver():
        try:
            result['received'] = receiver.receive()
        except Exception as e:
            result['errors'].append(('receiver', str(e)))

    start = time.time()
    t_recv = threading.Thread(target=run_receiver, daemon=True)
    t_send = threading.Thread(target=run_sender, daemon=True)

    t_recv.start()
    time.sleep(0.02)          # let receiver start listening first
    t_send.start()

    t_send.join(timeout=timeout)
    remaining = max(1.0, timeout - (time.time() - start))
    t_recv.join(timeout=remaining)
    elapsed = time.time() - start

    channel.shutdown()

    if result['errors']:
        raise RuntimeError(f"Transfer failed: {result['errors']}")
    if t_send.is_alive() or t_recv.is_alive():
        raise RuntimeError(f"Transfer timed out after {elapsed:.1f}s")
    if result['received'] is None:
        raise RuntimeError("Receiver returned None")

    return result['received'], result['stats'], elapsed
