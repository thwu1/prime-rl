
"""Standalone parser for the VitalDB .vital binary recording format.

Parses gzip-compressed binary files containing multi-device perioperative
monitoring data without depending on the vitaldb Python package.
"""

import gzip
import os
import struct

import numpy as np

# ---------------------------------------------------------------------------
# Format constants
# ---------------------------------------------------------------------------

# Data format code -> (struct format char, byte size)
FMT_TYPE_LEN = {
    1: ('f', 4),   # float32
    2: ('d', 8),   # float64
    3: ('b', 1),   # signed byte
    4: ('B', 1),   # unsigned byte
    5: ('h', 2),   # signed short
    6: ('H', 2),   # unsigned short
    7: ('l', 4),   # signed long (int32)
    8: ('L', 4),   # unsigned long (uint32)
}

TYPE_NAMES = {1: 'wav', 2: 'num', 5: 'str'}

# Pre-compiled struct unpackers for speed
_S_B = struct.Struct('<B')
_S_H = struct.Struct('<H')
_S_h = struct.Struct('<h')
_S_L = struct.Struct('<L')
_S_f = struct.Struct('<f')
_S_d = struct.Struct('<d')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unpack_str(buf, pos):
    """Unpack a length-prefixed UTF-8 string from *buf* at *pos*."""
    slen = _S_L.unpack_from(buf, pos)[0]
    pos += 4
    val = buf[pos:pos + slen].decode('utf-8', 'ignore')
    return val, pos + slen


class _Track:
    """Internal track representation."""
    __slots__ = ('name', 'ttype', 'fmt', 'unit', 'srate', 'gain', 'offset',
                 'dname', 'recs')

    def __init__(self, name, ttype, fmt, unit='', srate=0.0, gain=1.0,
                 offset=0.0, dname=''):
        self.name = name
        self.ttype = ttype
        self.fmt = fmt
        self.unit = unit
        self.srate = srate
        self.gain = gain
        self.offset = offset
        self.dname = dname
        self.recs = []  # list of {'dt': float, 'val': ...}


# ---------------------------------------------------------------------------
# Core loader — reads the .vital binary stream
# ---------------------------------------------------------------------------

_cache = {}


def _load_vital(path):
    """Parse a .vital file and return internal structures.

    Returns (tracks, devices, tid_dtnames, dtstart, dtend)
    where *tracks* maps tid -> _Track, *devices* maps did -> dict,
    *tid_dtnames* maps tid -> full "DeviceName/TrackName" string.
    """
    abspath = os.path.abspath(path)
    if abspath in _cache:
        return _cache[abspath]

    with open(path, 'rb') as raw_f:
        f = gzip.GzipFile(fileobj=raw_f)

        # ---- Header ----
        magic = f.read(4)
        if magic != b'VITA':
            raise ValueError(f'Not a .vital file (magic={magic!r})')

        f.read(4)  # version (ignored)
        hdr_len = _S_H.unpack_from(f.read(2), 0)[0]
        header = f.read(hdr_len)

        dgmt = _S_h.unpack_from(header, 0)[0]
        dtstart = dtend = 0.0
        packed = False
        if hdr_len >= 26:
            dtstart = _S_d.unpack_from(header, 10)[0]
            dtend = _S_d.unpack_from(header, 18)[0]
        if hdr_len >= 27:
            packed = (header[26] == 1)

        devices = {}        # did -> {'name': str, 'type': str}
        tracks = {}         # tid -> _Track
        tid_dtnames = {}    # tid -> full name

        # ---- Packet loop ----
        try:
            while True:
                pkt_hdr = f.read(5)
                if len(pkt_hdr) < 5:
                    break
                ptype = pkt_hdr[0]
                plen = _S_L.unpack_from(pkt_hdr, 1)[0]

                if not packed and plen > 10_000_000:
                    break

                buf = f.read(plen)
                if len(buf) < plen:
                    break
                pos = 0

                # -- Device info (type 9) --
                if ptype == 9:
                    did = _S_L.unpack_from(buf, pos)[0]; pos += 4
                    devtype, pos = _unpack_str(buf, pos)
                    devname, pos = _unpack_str(buf, pos)
                    if not devname:
                        devname = devtype
                    devices[did] = {'name': devname, 'type': devtype}

                # -- Track info (type 0) --
                elif ptype == 0:
                    tid = _S_H.unpack_from(buf, pos)[0]; pos += 2
                    trktype = buf[pos]; pos += 1
                    fmt_code = buf[pos]; pos += 1

                    if (trktype in (1, 2)) and fmt_code not in FMT_TYPE_LEN:
                        continue

                    tname, pos = _unpack_str(buf, pos)
                    unit = ''
                    srate = gain_val = 0.0
                    gain_val = 1.0
                    offset_val = 0.0
                    did_ref = 0

                    if plen > pos:
                        unit, pos = _unpack_str(buf, pos)
                    if plen > pos:
                        pos += 4  # mindisp
                    if plen > pos:
                        pos += 4  # maxdisp
                    if plen > pos:
                        pos += 4  # color
                    if plen > pos:
                        srate = _S_f.unpack_from(buf, pos)[0]; pos += 4
                    if plen > pos:
                        gain_val = _S_d.unpack_from(buf, pos)[0]; pos += 8
                    if plen > pos:
                        offset_val = _S_d.unpack_from(buf, pos)[0]; pos += 8
                    if plen > pos:
                        pos += 1  # montype
                    if plen > pos:
                        did_ref = _S_L.unpack_from(buf, pos)[0]; pos += 4

                    dname = ''
                    if did_ref and did_ref in devices:
                        dname = devices[did_ref]['name']
                    dtname = f'{dname}/{tname}' if dname else tname

                    trk = _Track(tname, trktype, fmt_code, unit=unit,
                                 srate=srate, gain=gain_val, offset=offset_val,
                                 dname=dname)
                    tracks[tid] = trk
                    tid_dtnames[tid] = dtname

                # -- Data record (type 1) --
                elif ptype == 1:
                    if len(buf) < 12:
                        continue
                    infolen = _S_H.unpack_from(buf, pos)[0]; pos += 2
                    dt = _S_d.unpack_from(buf, pos)[0]; pos += 8
                    tid = _S_H.unpack_from(buf, pos)[0]; pos += 2
                    pos = 2 + infolen  # jump past info section

                    if tid not in tracks:
                        continue
                    trk = tracks[tid]

                    if dtstart == 0 or (dt > 0 and dt < dtstart):
                        dtstart = dt
                    if dt > dtend:
                        dtend = dt

                    if trk.ttype == 1:  # waveform
                        fmtcode, fmtlen = FMT_TYPE_LEN[trk.fmt]
                        if len(buf) < pos + 4:
                            continue
                        nsamp = _S_L.unpack_from(buf, pos)[0]; pos += 4
                        if len(buf) < pos + nsamp * fmtlen:
                            continue
                        samps = np.frombuffer(buf, dtype=np.dtype(fmtcode),
                                              count=nsamp, offset=pos).copy()
                        trk.recs.append({'dt': dt, 'val': samps})
                        if trk.srate > 0:
                            rec_end = dt + nsamp / trk.srate
                            if rec_end > dtend:
                                dtend = rec_end

                    elif trk.ttype == 2:  # numeric
                        fmtcode, fmtlen = FMT_TYPE_LEN[trk.fmt]
                        if len(buf) < pos + fmtlen:
                            continue
                        val = struct.unpack_from(fmtcode, buf, pos)[0]
                        trk.recs.append({'dt': dt, 'val': val})

                    elif trk.ttype == 5:  # string
                        pos += 4  # skip 4-byte field
                        if len(buf) < pos + 4:
                            continue
                        s, pos = _unpack_str(buf, pos)
                        trk.recs.append({'dt': dt, 'val': s})

                # -- Command (type 6) -- skip for now
                elif ptype == 6:
                    pass

        except EOFError:
            pass

    result = (tracks, devices, tid_dtnames, dtstart, dtend)
    _cache[abspath] = result
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(path):
    """Parse a .vital file and return metadata.

    Returns dict with keys: tracks, devices, duration_sec, dtstart, dtend.
    """
    tracks, devices, tid_dtnames, dtstart, dtend = _load_vital(path)

    track_list = []
    for tid, trk in tracks.items():
        dtname = tid_dtnames.get(tid, trk.name)
        track_list.append({
            'name': dtname,
            'type': TYPE_NAMES.get(trk.ttype, 'unknown'),
            'unit': trk.unit,
            'srate': float(trk.srate),
            'fmt': trk.fmt,
            'gain': float(trk.gain),
            'offset': float(trk.offset),
            'num_records': len(trk.recs),
        })

    device_list = [{'name': d['name'], 'type': d['type']}
                   for d in devices.values()]

    return {
        'tracks': track_list,
        'devices': device_list,
        'duration_sec': (dtend - dtstart) if dtend > dtstart else 0.0,
        'dtstart': dtstart,
        'dtend': dtend,
    }


def get_track_samples(path, track_name, interval):
    """Return a dense float32 array of track samples at the given interval.

    Parameters
    ----------
    path : str
        Local path to a .vital file.
    track_name : str
        Full "DeviceName/TrackName" string, or just "TrackName" (suffix match).
    interval : float
        Sampling interval in seconds (e.g. 1.0 for 1 Hz, 0.002 for 500 Hz).

    Returns
    -------
    numpy.ndarray
        1-D float32 array with NaN for missing data.
    """
    tracks, devices, tid_dtnames, dtstart, dtend = _load_vital(path)

    # Find the track by name (exact match first, then suffix match)
    target = None
    for tid, trk in tracks.items():
        dtname = tid_dtnames.get(tid, trk.name)
        if dtname == track_name:
            target = trk
            break
    if target is None:
        for tid, trk in tracks.items():
            dtname = tid_dtnames.get(tid, trk.name)
            if dtname.endswith(track_name) or track_name.endswith(trk.name):
                target = trk
                break

    if dtend <= dtstart:
        return np.array([], dtype=np.float32)

    nret = int(np.ceil((dtend - dtstart) / interval))
    if nret <= 0:
        return np.array([], dtype=np.float32)

    if target is None:
        return np.full(nret, np.nan, dtype=np.float32)

    # ---- Numeric track ----
    if target.ttype == 2:
        ret = np.full(nret, np.nan, dtype=np.float32)
        for rec in target.recs:
            idx = int((rec['dt'] - dtstart) / interval)
            if 0 <= idx < nret:
                ret[idx] = float(rec['val'])
        return ret

    # ---- Waveform track ----
    if target.ttype == 1:
        nsamp = int(np.ceil((dtend - dtstart) * target.srate))
        if nsamp <= 0:
            return np.full(nret, np.nan, dtype=np.float32)

        ret = np.full(nsamp, np.nan, dtype=np.float32)
        for rec in target.recs:
            sidx = int(np.ceil((rec['dt'] - dtstart) * target.srate))
            vals = rec['val'].astype(np.float32)
            eidx = sidx + len(vals)
            srecidx = 0
            erecidx = len(vals)
            if sidx < 0:
                srecidx -= sidx
                sidx = 0
            if eidx > nsamp:
                erecidx -= (eidx - nsamp)
                eidx = nsamp
            if eidx > sidx:
                ret[sidx:eidx] = vals[srecidx:erecidx]

        # Apply gain/offset for integer formats (fmt > 2)
        if target.fmt > 2:
            ret *= target.gain
            ret += target.offset

        # Filter invalid values
        ret[np.isinf(ret) | (ret > 4e9)] = np.nan

        # Resample to target interval if rates differ
        target_srate = round(1.0 / interval)
        if abs(target.srate - target_srate) > 0.01:
            indices = np.linspace(0, nsamp - 1, nret).astype(np.int64)
            ret = np.take(ret, indices)

        return ret

    # ---- String track (return NaN) ----
    return np.full(nret, np.nan, dtype=np.float32)
