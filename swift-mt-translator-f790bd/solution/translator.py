#!/usr/bin/env python3
"""MT103 to pacs.008.001.08 CBPR+ translator.

"""

import sys
import re
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
from datetime import datetime

NS_BAH = "urn:iso:std:iso:20022:tech:xsd:head.001.001.03"
NS_PACS = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"

ET.register_namespace('', NS_BAH)
ET.register_namespace('pacs', NS_PACS)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def normalize_bic(bic):
    bic = bic.strip()
    if len(bic) == 8:
        return bic + 'XXX'
    return bic


def parse_date(yymmdd):
    yy = int(yymmdd[:2])
    yyyy = 2000 + yy if yy < 80 else 1900 + yy
    return f"{yyyy}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def parse_amount(s):
    r = s.replace(',', '.')
    if r.endswith('.'):
        r += '00'
    return r


def is_iban(acct):
    return bool(re.match(r'^[A-Z]{2}\d{2}[A-Za-z0-9]+$', acct)) and 15 <= len(acct) <= 34


def bah(tag):
    return f'{{{NS_BAH}}}{tag}'


def pacs(tag):
    return f'{{{NS_PACS}}}{tag}'


# ---------------------------------------------------------------------------
# MT103 Parsing
# ---------------------------------------------------------------------------

def parse_mt103(text):
    msg = {}
    m = re.search(r'\{1:(.+?)\}', text)
    if m:
        msg['block1'] = m.group(1)
    m = re.search(r'\{2:(.+?)\}', text)
    if m:
        msg['block2'] = m.group(1)
    m = re.search(r'\{3:((?:\{[^}]+\})+)\}', text)
    if m:
        msg['block3'] = {}
        for sm in re.finditer(r'\{(\d+):([^}]+)\}', m.group(1)):
            msg['block3'][sm.group(1)] = sm.group(2)
    m = re.search(r'\{4:\s*\n(.*?)\n-\}', text, re.DOTALL)
    if m:
        msg['fields'] = _parse_fields(m.group(1))
    return msg


def _parse_fields(text):
    fields = []
    tag = val = None
    for line in text.split('\n'):
        m = re.match(r'^:(\d{2}[A-Z]?):(.*)$', line)
        if m:
            if tag:
                fields.append((tag, val))
            tag, val = m.group(1), m.group(2)
        elif tag is not None:
            val += '\n' + line
    if tag:
        fields.append((tag, val))
    return fields


def get_sender_bic(b1):
    bic8 = b1[3:11]
    branch = b1[12:15]
    return normalize_bic(bic8) if branch == 'XXX' else bic8 + branch


def get_receiver_info(b2):
    bic8 = b2[4:12]
    branch = b2[13:16]
    prio = b2[16] if len(b2) > 16 else 'N'
    rcv = normalize_bic(bic8) if branch == 'XXX' else bic8 + branch
    return rcv, 'HIGH' if prio == 'U' else 'NORM'


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def parse_agent_a(val):
    lines = val.split('\n')
    r = {}
    if lines[0].startswith('/'):
        r['account'] = lines[0][1:]
        lines = lines[1:]
    if lines:
        r['bic'] = normalize_bic(lines[0])
    return r


def parse_agent_d(val):
    lines = val.split('\n')
    r = {}
    if lines[0].startswith('/'):
        r['account'] = lines[0][1:]
        lines = lines[1:]
    if lines:
        r['name'] = lines[0]
    if len(lines) > 1:
        r['addr'] = lines[1:]
    return r


def parse_party_k(val):
    lines = val.split('\n')
    r = {}
    if lines[0].startswith('/'):
        r['account'] = lines[0][1:]
        lines = lines[1:]
    if lines:
        r['name'] = lines[0]
    if len(lines) > 1:
        r['addr'] = lines[1:]
    return r


def parse_party_f(val):
    lines = val.split('\n')
    r = {}
    first = lines[0]
    if first.startswith('/'):
        r['account'] = first[1:]
        detail = lines[1:]
    else:
        parts = first.split('/')
        if len(parts) >= 3 and parts[0] in ('TXID', 'PASSPORT', 'DRLC', 'EMPL',
                                              'CCPT', 'ARNU', 'NIDN', 'SOSE', 'CUST'):
            r['id_type'] = parts[0]
            r['id_country'] = parts[1]
            r['id_value'] = parts[2]
        detail = lines[1:]

    for ln in detail:
        if ln.startswith('1/'):
            r['name'] = ln[2:]
        elif ln.startswith('2/'):
            r['address'] = ln[2:]
        elif ln.startswith('3/'):
            p = ln[2:].split('/', 1)
            r['country'] = p[0]
            if len(p) > 1:
                r['town'] = p[1]
        elif ln.startswith('4/'):
            r['birth_date'] = ln[2:]
        elif ln.startswith('5/'):
            r['birth_place'] = ln[2:]
    return r


def parse_party_a(val):
    lines = val.split('\n')
    r = {}
    if lines[0].startswith('/'):
        r['account'] = lines[0][1:]
        lines = lines[1:]
    if lines:
        r['bic'] = normalize_bic(lines[0])
    return r


def parse_32a(val):
    return parse_date(val[:6]), val[6:9], parse_amount(val[9:])


def parse_33b(val):
    return val[:3], parse_amount(val[3:])


def parse_13c(val):
    m = re.match(r'/(\w+)/(\d{4})([+-]\d{4})', val)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None


def parse_70(val):
    strd, ustrd = [], []
    for ln in val.split('\n'):
        if ln.startswith('/INV/'):
            strd.append(('CINV', ln[5:]))
        elif ln.startswith('/RFB/'):
            strd.append(('RFB', ln[5:]))
        elif ln.startswith('/ROC/'):
            strd.append(('ROC', ln[5:]))
        elif ln.startswith('/IPI/'):
            strd.append(('IPI', ln[5:]))
        elif ln.startswith('/TSU/'):
            strd.append(('TSU', ln[5:]))
        else:
            ustrd.append(ln)
    return strd, ustrd


def parse_72(val):
    ins_bic = bnf_text = None
    other = []
    cur = None
    for ln in val.split('\n'):
        if ln.startswith('/INS/'):
            ins_bic = normalize_bic(ln[5:])
            cur = 'ins'
        elif ln.startswith('/BNF/'):
            bnf_text = ln[5:]
            cur = 'bnf'
        elif ln.startswith('//'):
            txt = ln[2:]
            if cur == 'bnf':
                bnf_text += ' ' + txt
            else:
                other.append(txt)
        elif ln.startswith('/'):
            other.append(ln)
            cur = 'other'
        else:
            other.append(ln)
    return ins_bic, bnf_text, other


def parse_77b(val):
    items = []
    for ln in val.split('\n'):
        if ln.startswith('/ORDERRES/'):
            rest = ln[10:]
            cc, _, info = rest.partition('//')
            items.append(('DEBT', cc, info))
        elif ln.startswith('/BENRES/'):
            rest = ln[8:]
            cc, _, info = rest.partition('//')
            items.append(('CRED', cc, info))
    return items


# ---------------------------------------------------------------------------
# XML Builder
# ---------------------------------------------------------------------------

def add_fi(parent, tag, bicfi):
    el = SubElement(parent, tag)
    fi = SubElement(el, pacs('FinInstnId'))
    SubElement(fi, pacs('BICFI')).text = bicfi
    return el


def add_acct(parent, tag, acct_id):
    acct = SubElement(parent, tag)
    aid = SubElement(acct, pacs('Id'))
    if is_iban(acct_id):
        SubElement(aid, pacs('IBAN')).text = acct_id
    else:
        othr = SubElement(aid, pacs('Othr'))
        SubElement(othr, pacs('Id')).text = acct_id
    return acct


def build_xml(msg):
    b1 = msg.get('block1', '')
    b2 = msg.get('block2', '')
    b3 = msg.get('block3', {})
    fields = msg.get('fields', [])

    sender = get_sender_bic(b1)
    receiver, priority = get_receiver_info(b2)
    biz_msg_idr = b3.get('108', '')
    stp = b3.get('119', '')
    uetr = b3.get('121', '')

    # Index fields (last wins for single-value, list for repeatable)
    fd = {}
    fl = {}
    for t, v in fields:
        if t in fd:
            fl.setdefault(t, [fd[t]]).append(v)
        fd[t] = v

    f20 = fd.get('20', '')
    f13C = fd.get('13C', '')
    f23B = fd.get('23B', '')
    f23E_all = fl.get('23E', [fd['23E']] if '23E' in fd else [])
    f26T = fd.get('26T', '')
    f32A = fd.get('32A', '')
    f33B = fd.get('33B', '')
    f36 = fd.get('36', '')
    f50A = fd.get('50A', '')
    f50F = fd.get('50F', '')
    f50K = fd.get('50K', '')
    f52A = fd.get('52A', '')
    f52D = fd.get('52D', '')
    f53A = fd.get('53A', '')
    f53B = fd.get('53B', '')
    f54A = fd.get('54A', '')
    f56A = fd.get('56A', '')
    f56D = fd.get('56D', '')
    f57A = fd.get('57A', '')
    f57D = fd.get('57D', '')
    f59 = fd.get('59', '')
    f59A = fd.get('59A', '')
    f59F = fd.get('59F', '')
    f70 = fd.get('70', '')
    f71A = fd.get('71A', '')
    f71F_all = fl.get('71F', [fd['71F']] if '71F' in fd else [])
    f71G = fd.get('71G', '')
    f72 = fd.get('72', '')
    f77B = fd.get('77B', '')

    # Settlement method
    has53 = bool(f53A or f53B)
    has54 = bool(f54A)
    sttlm_mtd = 'COVE' if (has53 and has54) else ('INGA' if has53 else 'INDA')

    # Parse 32A
    sdt, sccy, samt = parse_32a(f32A) if f32A else ('', '', '')

    # Parse 70
    f70_strd, f70_ustrd = parse_70(f70) if f70 else ([], [])
    # ROC override for InstrId
    roc_ref = None
    for tp, ref in f70_strd:
        if tp == 'ROC':
            roc_ref = ref

    # === Build XML ===
    root = Element(bah('BizMsg'))

    # -- AppHdr --
    hdr = SubElement(root, bah('AppHdr'))
    fr = SubElement(hdr, bah('Fr'))
    fi = SubElement(fr, bah('FIId'))
    fii = SubElement(fi, bah('FinInstnId'))
    SubElement(fii, bah('BICFI')).text = sender

    to = SubElement(hdr, bah('To'))
    fi = SubElement(to, bah('FIId'))
    fii = SubElement(fi, bah('FinInstnId'))
    SubElement(fii, bah('BICFI')).text = receiver

    SubElement(hdr, bah('BizMsgIdr')).text = biz_msg_idr
    SubElement(hdr, bah('MsgDefIdr')).text = 'pacs.008.001.08'
    SubElement(hdr, bah('BizSvc')).text = 'swift.cbprplus.02'
    SubElement(hdr, bah('CreDt')).text = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    SubElement(hdr, bah('Prty')).text = priority

    # -- Document --
    doc = SubElement(root, pacs('Document'))
    cdt_trf_root = SubElement(doc, pacs('FIToFICstmrCdtTrf'))

    # -- GrpHdr --
    grp = SubElement(cdt_trf_root, pacs('GrpHdr'))
    SubElement(grp, pacs('MsgId')).text = f20
    SubElement(grp, pacs('CreDtTm')).text = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    SubElement(grp, pacs('NbOfTxs')).text = '1'

    si = SubElement(grp, pacs('SttlmInf'))
    SubElement(si, pacs('SttlmMtd')).text = sttlm_mtd

    if f53A:
        ag = parse_agent_a(f53A)
        agt = SubElement(si, pacs('InstgRmbrsmntAgt'))
        fi = SubElement(agt, pacs('FinInstnId'))
        if 'bic' in ag:
            SubElement(fi, pacs('BICFI')).text = ag['bic']
        if 'account' in ag:
            add_acct(si, pacs('InstgRmbrsmntAgtAcct'), ag['account'])
    elif f53B:
        ag = parse_agent_a(f53B)
        if 'account' in ag:
            sa = SubElement(si, pacs('SttlmAcct'))
            aid = SubElement(sa, pacs('Id'))
            othr = SubElement(aid, pacs('Othr'))
            SubElement(othr, pacs('Id')).text = ag['account']

    if f54A:
        ag = parse_agent_a(f54A)
        agt = SubElement(si, pacs('InstdRmbrsmntAgt'))
        fi = SubElement(agt, pacs('FinInstnId'))
        if 'bic' in ag:
            SubElement(fi, pacs('BICFI')).text = ag['bic']
        if 'account' in ag:
            add_acct(si, pacs('InstdRmbrsmntAgtAcct'), ag['account'])

    add_fi(grp, pacs('InstgAgt'), sender)
    add_fi(grp, pacs('InstdAgt'), receiver)

    # -- CdtTrfTxInf --
    tx = SubElement(cdt_trf_root, pacs('CdtTrfTxInf'))

    # PmtId
    pid = SubElement(tx, pacs('PmtId'))
    SubElement(pid, pacs('InstrId')).text = roc_ref if roc_ref else f20
    SubElement(pid, pacs('EndToEndId')).text = 'NOTPROVIDED'
    SubElement(pid, pacs('TxId')).text = f20
    if uetr:
        SubElement(pid, pacs('UETR')).text = uetr

    # PmtTpInf
    instr_prty = priority
    svc_cd = 'G004' if stp == 'STP' else None
    lcl_cd = f26T.strip() if f26T else None
    ctgy_cd = None
    for e23 in f23E_all:
        c = e23.strip()
        if c == 'CORT':
            ctgy_cd = 'CORT'
        elif c == 'INTC':
            ctgy_cd = 'INTC'
        elif c == 'SPRI':
            instr_prty = 'HIGH'
        elif c == 'SSTD':
            instr_prty = 'NORM'

    if instr_prty or svc_cd or lcl_cd or ctgy_cd:
        pti = SubElement(tx, pacs('PmtTpInf'))
        SubElement(pti, pacs('InstrPrty')).text = instr_prty
        if svc_cd:
            sl = SubElement(pti, pacs('SvcLvl'))
            SubElement(sl, pacs('Cd')).text = svc_cd
        if lcl_cd:
            li = SubElement(pti, pacs('LclInstrm'))
            SubElement(li, pacs('Cd')).text = lcl_cd
        if ctgy_cd:
            cp = SubElement(pti, pacs('CtgyPurp'))
            SubElement(cp, pacs('Cd')).text = ctgy_cd

    # IntrBkSttlmAmt + Date
    amt_el = SubElement(tx, pacs('IntrBkSttlmAmt'))
    amt_el.set('Ccy', sccy)
    amt_el.text = samt
    SubElement(tx, pacs('IntrBkSttlmDt')).text = sdt

    # SttlmTmIndctn
    if f13C:
        code, tm, tz = parse_13c(f13C)
        if code:
            sti = SubElement(tx, pacs('SttlmTmIndctn'))
            dt_val = f"{sdt}T{tm[:2]}:{tm[2:]}:00{tz[:3]}:{tz[3:]}"
            if code in ('CLSTIME', 'SNDTIME'):
                SubElement(sti, pacs('DbtDtTm')).text = dt_val
            elif code == 'RNCTIME':
                SubElement(sti, pacs('CdtDtTm')).text = dt_val

    # InstdAmt
    if f33B:
        iccy, iamt = parse_33b(f33B)
        iel = SubElement(tx, pacs('InstdAmt'))
        iel.set('Ccy', iccy)
        iel.text = iamt

    # XchgRate
    if f36:
        SubElement(tx, pacs('XchgRate')).text = parse_amount(f36)

    # ChrgBr
    chrg_map = {'BEN': 'CRED', 'OUR': 'DEBT', 'SHA': 'SHAR'}
    if f71A:
        SubElement(tx, pacs('ChrgBr')).text = chrg_map.get(f71A.strip(), 'SHAR')

    # ChrgsInf from 71F
    for fv in f71F_all:
        if fv:
            cccy, camt = parse_33b(fv)
            ci = SubElement(tx, pacs('ChrgsInf'))
            ca = SubElement(ci, pacs('Amt'))
            ca.set('Ccy', cccy)
            ca.text = camt
            cag = SubElement(ci, pacs('Agt'))
            cfi = SubElement(cag, pacs('FinInstnId'))
            SubElement(cfi, pacs('BICFI')).text = sender

    # ChrgsInf from 71G
    if f71G:
        cccy, camt = parse_33b(f71G)
        ci = SubElement(tx, pacs('ChrgsInf'))
        ca = SubElement(ci, pacs('Amt'))
        ca.set('Ccy', cccy)
        ca.text = camt
        cag = SubElement(ci, pacs('Agt'))
        cfi = SubElement(cag, pacs('FinInstnId'))
        SubElement(cfi, pacs('BICFI')).text = receiver

    # PrvsInstgAgt1
    if f72:
        ins_bic, bnf_txt, other_72 = parse_72(f72)
        if ins_bic:
            add_fi(tx, pacs('PrvsInstgAgt1'), ins_bic)

    # InstgAgt / InstdAgt (within CdtTrfTxInf)
    add_fi(tx, pacs('InstgAgt'), sender)
    add_fi(tx, pacs('InstdAgt'), receiver)

    # IntrmyAgt1
    if f56A:
        ag = parse_agent_a(f56A)
        if 'bic' in ag:
            add_fi(tx, pacs('IntrmyAgt1'), ag['bic'])
        if 'account' in ag:
            add_acct(tx, pacs('IntrmyAgt1Acct'), ag['account'])
    elif f56D:
        ag = parse_agent_d(f56D)
        ia = SubElement(tx, pacs('IntrmyAgt1'))
        fi = SubElement(ia, pacs('FinInstnId'))
        if 'name' in ag:
            SubElement(fi, pacs('Nm')).text = ag['name']
        if 'addr' in ag:
            addr = SubElement(fi, pacs('PstlAdr'))
            for al in ag['addr']:
                SubElement(addr, pacs('AdrLine')).text = al

    # Dbtr
    dbtr = SubElement(tx, pacs('Dbtr'))
    dbtr_acct_val = None
    if f50K:
        p = parse_party_k(f50K)
        dbtr_acct_val = p.get('account')
        if 'name' in p:
            SubElement(dbtr, pacs('Nm')).text = p['name']
        if 'addr' in p:
            pa = SubElement(dbtr, pacs('PstlAdr'))
            for al in p['addr']:
                SubElement(pa, pacs('AdrLine')).text = al
    elif f50F:
        p = parse_party_f(f50F)
        dbtr_acct_val = p.get('account')
        if 'name' in p:
            SubElement(dbtr, pacs('Nm')).text = p['name']
        if 'address' in p or 'country' in p:
            pa = SubElement(dbtr, pacs('PstlAdr'))
            if 'town' in p:
                SubElement(pa, pacs('TwnNm')).text = p['town']
            if 'country' in p:
                SubElement(pa, pacs('Ctry')).text = p['country']
            if 'address' in p:
                SubElement(pa, pacs('AdrLine')).text = p['address']
        if 'id_type' in p:
            ident = SubElement(dbtr, pacs('Id'))
            oid = SubElement(ident, pacs('OrgId'))
            othr = SubElement(oid, pacs('Othr'))
            SubElement(othr, pacs('Id')).text = p['id_value']
            sn = SubElement(othr, pacs('SchmeNm'))
            SubElement(sn, pacs('Cd')).text = p['id_type']
            if 'id_country' in p:
                SubElement(othr, pacs('Issr')).text = p['id_country']
    elif f50A:
        p = parse_party_a(f50A)
        dbtr_acct_val = p.get('account')
        if 'bic' in p:
            ident = SubElement(dbtr, pacs('Id'))
            oid = SubElement(ident, pacs('OrgId'))
            SubElement(oid, pacs('AnyBIC')).text = p['bic']

    # DbtrAcct
    if dbtr_acct_val:
        add_acct(tx, pacs('DbtrAcct'), dbtr_acct_val)

    # DbtrAgt
    if f52A:
        ag = parse_agent_a(f52A)
        add_fi(tx, pacs('DbtrAgt'), ag.get('bic', sender))
        if 'account' in ag:
            add_acct(tx, pacs('DbtrAgtAcct'), ag['account'])
    elif f52D:
        ag = parse_agent_d(f52D)
        da = SubElement(tx, pacs('DbtrAgt'))
        fi = SubElement(da, pacs('FinInstnId'))
        if 'name' in ag:
            SubElement(fi, pacs('Nm')).text = ag['name']
        if 'addr' in ag:
            addr = SubElement(fi, pacs('PstlAdr'))
            for al in ag['addr']:
                SubElement(addr, pacs('AdrLine')).text = al
    else:
        add_fi(tx, pacs('DbtrAgt'), sender)

    # CdtrAgt + CdtrAgtAcct
    if f57A:
        ag = parse_agent_a(f57A)
        add_fi(tx, pacs('CdtrAgt'), ag.get('bic', receiver))
        if 'account' in ag:
            add_acct(tx, pacs('CdtrAgtAcct'), ag['account'])
    elif f57D:
        ag = parse_agent_d(f57D)
        ca = SubElement(tx, pacs('CdtrAgt'))
        fi = SubElement(ca, pacs('FinInstnId'))
        if 'name' in ag:
            SubElement(fi, pacs('Nm')).text = ag['name']
        if 'addr' in ag:
            addr = SubElement(fi, pacs('PstlAdr'))
            for al in ag['addr']:
                SubElement(addr, pacs('AdrLine')).text = al
        if 'account' in ag:
            add_acct(tx, pacs('CdtrAgtAcct'), ag['account'])
    else:
        add_fi(tx, pacs('CdtrAgt'), receiver)

    # Cdtr + CdtrAcct
    cdtr = SubElement(tx, pacs('Cdtr'))
    cdtr_acct_val = None
    if f59:
        p = parse_party_k(f59)
        cdtr_acct_val = p.get('account')
        if 'name' in p:
            SubElement(cdtr, pacs('Nm')).text = p['name']
        if 'addr' in p:
            pa = SubElement(cdtr, pacs('PstlAdr'))
            for al in p['addr']:
                SubElement(pa, pacs('AdrLine')).text = al
    elif f59F:
        p = parse_party_f(f59F)
        cdtr_acct_val = p.get('account')
        if 'name' in p:
            SubElement(cdtr, pacs('Nm')).text = p['name']
        if 'address' in p or 'country' in p:
            pa = SubElement(cdtr, pacs('PstlAdr'))
            if 'town' in p:
                SubElement(pa, pacs('TwnNm')).text = p['town']
            if 'country' in p:
                SubElement(pa, pacs('Ctry')).text = p['country']
            if 'address' in p:
                SubElement(pa, pacs('AdrLine')).text = p['address']
    elif f59A:
        lines = f59A.split('\n')
        if lines[0].startswith('/'):
            cdtr_acct_val = lines[0][1:]
            lines = lines[1:]
        if lines:
            ident = SubElement(cdtr, pacs('Id'))
            oid = SubElement(ident, pacs('OrgId'))
            SubElement(oid, pacs('AnyBIC')).text = normalize_bic(lines[0])

    if cdtr_acct_val:
        add_acct(tx, pacs('CdtrAcct'), cdtr_acct_val)

    # InstrForCdtrAgt (from 23E codes)
    for e23 in f23E_all:
        c = e23.strip()
        if c in ('CHQB', 'HOLD', 'PHOB', 'TELB', 'SDVA'):
            icag = SubElement(tx, pacs('InstrForCdtrAgt'))
            SubElement(icag, pacs('Cd')).text = c

    # InstrForCdtrAgt from 72 /BNF/
    if f72:
        ins_bic, bnf_txt, other_72 = parse_72(f72)
        if bnf_txt:
            icag = SubElement(tx, pacs('InstrForCdtrAgt'))
            SubElement(icag, pacs('InstrInf')).text = bnf_txt

    # InstrForNxtAgt from 72 other
    if f72:
        ins_bic, bnf_txt, other_72 = parse_72(f72)
        for ln in other_72:
            if ln.strip():
                ina = SubElement(tx, pacs('InstrForNxtAgt'))
                SubElement(ina, pacs('InstrInf')).text = ln

    # RgltryRptg
    if f77B:
        for ind, cc, info in parse_77b(f77B):
            rr = SubElement(tx, pacs('RgltryRptg'))
            SubElement(rr, pacs('DbtCdtRptgInd')).text = ind
            auth = SubElement(rr, pacs('Authrty'))
            SubElement(auth, pacs('Ctry')).text = cc
            if info:
                dtls = SubElement(rr, pacs('Dtls'))
                SubElement(dtls, pacs('Inf')).text = info

    # RmtInf
    if f70:
        has_ustrd = any(u.strip() for u in f70_ustrd)
        has_strd = any(tp in ('CINV', 'RFB') for tp, _ in f70_strd)
        if has_ustrd or has_strd:
            rmt = SubElement(tx, pacs('RmtInf'))
            for u in f70_ustrd:
                if u.strip():
                    SubElement(rmt, pacs('Ustrd')).text = u
            for tp, ref in f70_strd:
                if tp == 'CINV':
                    strd = SubElement(rmt, pacs('Strd'))
                    rdi = SubElement(strd, pacs('RfrdDocInf'))
                    t = SubElement(rdi, pacs('Tp'))
                    cop = SubElement(t, pacs('CdOrPrtry'))
                    SubElement(cop, pacs('Cd')).text = 'CINV'
                    SubElement(rdi, pacs('Nb')).text = ref
                elif tp == 'RFB':
                    strd = SubElement(rmt, pacs('Strd'))
                    cri = SubElement(strd, pacs('CdtrRefInf'))
                    SubElement(cri, pacs('Ref')).text = ref

    return root


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 mt103_to_pacs008.py <input.mt103> <output.xml>",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    xml_root = build_xml(parse_mt103(text))

    tree = ElementTree(xml_root)
    indent(tree, space='  ')
    with open(sys.argv[2], 'wb') as out:
        tree.write(out, xml_declaration=True, encoding='UTF-8')


if __name__ == '__main__':
    main()
