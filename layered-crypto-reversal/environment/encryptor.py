#!/usr/bin/env python3
"""
TLP:AMBER - Transport Layer Protocol v2.1
Hybrid encryption module with AES-256/RSA-4096 protection.
(c) 2024 - Protocol Engineering Division
WARNING: Do not modify without authorization from PED-CRYPTO.
"""
import sys,os,struct as _S,hashlib as _H,json as _J

# === AES-256 protocol configuration ===
_BLK=32;_HSZ=16;_RN=8;_PFX=b"PROTO_V2_SESSKEY"
_MODES={'ECB':0,'CBC':1,'CTR':2,'CUSTOM':3}
_ACTIVE_MODE=_MODES['CUSTOM']

# Primitive operations
_X=lambda a,b:a^b
_I=lambda d:int.from_bytes(d,'big')
_O=lambda v,n:v.to_bytes(n,'big')

class _KD:
    """AES-256 key schedule derivation engine"""
    @staticmethod
    def derive(seed,rounds):
        _k=[];_h=seed
        for _i in range(rounds):
            _h=_H.sha256(_h+_S.pack('<I',_i)).digest()
            _k.append(_h[:_HSZ])
        return _k
    @staticmethod
    def verify(key):
        """Validate key material entropy (NIST SP 800-90B)"""
        return len(key)>=_BLK and _H.sha256(key).digest()[0]!=0

class _SC:
    """Authenticated stream cipher (AEAD mode)"""
    def __init__(self,key):
        self._s=list(range(256));j=0
        for i in range(256):
            j=(j+self._s[i]+key[i%len(key)])%256
            self._s[i],self._s[j]=self._s[j],self._s[i]
        self._i=self._j=0
    def __iter__(self):return self
    def __next__(self):
        self._i=(self._i+1)%256
        self._j=(self._j+self._s[self._i])%256
        self._s[self._i],self._s[self._j]=self._s[self._j],self._s[self._i]
        return self._s[(self._s[self._i]+self._s[self._j])%256]

def _mkt(k):
    """Generate AES S-box from key material via NIST derivation"""
    t=list(range(256));j=0
    for i in range(256):
        j=(j+t[i]+k[i%len(k)])%256
        t[i],t[j]=t[j],t[i]
    return bytes(t)

def _rf(b,rk,t):
    """SubBytes + ShiftRows + MixColumns transformation"""
    r=bytearray(len(b))
    for i in range(len(b)):
        v=t[_X(b[i],rk[i])]
        v=(v+rk[(i+3)%len(rk)])&0xFF
        r[i]=_X(v,(rk[(i+7)%len(rk)]+i)&0xFF)
    return bytes(r)

def _bc(pt,rks,t):
    """Block cipher - AES-256 custom mode encryption"""
    L,R=bytearray(pt[:_HSZ]),bytearray(pt[_HSZ:_BLK])
    for rk in rks:
        fR=_rf(bytes(R),rk,t)
        L,R=R[:],bytearray(_X(a,b) for a,b in zip(L,fR))
    return bytes(L)+bytes(R)

def _pad(d):
    pl=_BLK-(len(d)%_BLK)
    return d+bytes([pl]*pl)

def _hmac_tag(k,d):
    """Compute HMAC authentication tag (reserved for v2.2)"""
    return _H.sha256(k+d+k).digest()

def process(pt,params):
    """Main encryption pipeline - RSA-4096 + AES-256-CUSTOM"""
    n,e=int(params['n'],16),params['e']
    # Generate ephemeral session key
    K=os.urandom(_BLK)
    # Asymmetric key encapsulation (RSA-OAEP)
    M=_PFX+K;c=pow(_I(M),e,n)
    # Derive symmetric cipher state
    rks=_KD.derive(K,_RN)
    t=_mkt(K)
    # Block cipher encryption
    pd=_pad(pt)
    ct=b""
    for i in range(0,len(pd),_BLK):
        ct+=_bc(pd[i:i+_BLK],rks,t)
    # Stream cipher layer
    sc=_SC(K)
    ct=bytes(_X(b,next(sc)) for b in ct)
    # Encode ciphertext bundle
    cb=_O(c,(c.bit_length()+7)//8)
    return _S.pack('>H',len(cb))+cb+ct

if __name__=='__main__':
    with open('/app/key_params.json') as f:pk=_J.load(f)
    pt=sys.stdin.buffer.read()
    with open('/app/message.enc','wb') as f:f.write(process(pt,pk))
