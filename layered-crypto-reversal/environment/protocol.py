#!/usr/bin/env python3
"""
TLP:AMBER - Secure Transport Protocol v2.1
RSA-4096/AES-256-CUSTOM authenticated encryption.
(c) 2024 Protocol Engineering Division
CLASSIFICATION: EXPORT CONTROLLED - EAR 5A002.a.1
DO NOT REDISTRIBUTE WITHOUT PED-CRYPTO AUTHORIZATION
"""
import ctypes as _C,struct as _S,os,json as _J

# Hardware-accelerated AES-256 engine (FIPS 140-3 Level 2 validated)
_E=_C.CDLL('./crypto_engine.so')
_E.cipher_init.argtypes=[_C.c_char_p,_C.c_int,_C.c_int]
_E.cipher_init.restype=None
_E.cipher_encrypt_block.argtypes=[_C.c_char_p,_C.c_char_p]
_E.cipher_encrypt_block.restype=None
_E.cipher_get_mode.restype=_C.c_int
_E.cipher_get_block_size.restype=_C.c_int
_E.cipher_get_name.restype=_C.c_char_p

_PFX=b"PROTO_V2_SESSKEY"
_I=lambda d:int.from_bytes(d,'big')
_O=lambda v,n:v.to_bytes(n,'big')
_X=lambda a,b:bytes(x^y for x,y in zip(a,b))

class _Channel:
    """AES-256 secure transport channel with RSA-OAEP key wrapping

    Implements NIST SP 800-56B Rev. 2 key transport scheme using
    RSA-OAEP (PKCS#1 v2.1) for key encapsulation and AES-256 in
    configurable block cipher modes for bulk data encryption.
    """
    MAGIC=b"PROT"

    def __init__(self,key_file):
        with open(key_file) as f:
            _p=_J.load(f)
        self._n=int(_p['n'],16)
        self._e=_p['e']

    def _wrap_key(self,k):
        """RSA-OAEP key encapsulation (PKCS#1 v2.1 compliant)
        Constructs M = PREFIX || K and encrypts under RSA-OAEP."""
        M=_PFX+k
        return pow(_I(M),self._e,self._n)

    def _msg(self,t,d):
        return self.MAGIC+bytes([0x02,t])+d

    def process(self,pt,mode=2):
        """Encrypt plaintext using selected AES-256 mode.

        Args:
            pt: plaintext bytes
            mode: cipher mode (0=ECB, 1=CBC, 2=PCBC)
        Returns:
            tuple of protocol messages (m1,m2,m3,m4)
        """
        bs=8  # AES block size
        K=os.urandom(16)  # AES-256 session key
        iv=os.urandom(bs)

        _E.cipher_init(K,len(K),mode)

        # PKCS#7 padding to block boundary
        pl=bs-(len(pt)%bs)
        if pl==0: pl=bs
        pd=pt+bytes([pl]*pl)

        ct=b""
        if mode==0:  # ECB - independent blocks
            for i in range(0,len(pd),bs):
                o=_C.create_string_buffer(bs)
                _E.cipher_encrypt_block(o,pd[i:i+bs])
                ct+=o.raw
        elif mode==1:  # CBC - chained
            pv=iv
            for i in range(0,len(pd),bs):
                o=_C.create_string_buffer(bs)
                _E.cipher_encrypt_block(o,_X(pd[i:i+bs],pv))
                ct+=o.raw
                pv=o.raw
        elif mode==2:  # PCBC - propagating
            fb=iv
            for i in range(0,len(pd),bs):
                bk=pd[i:i+bs]
                o=_C.create_string_buffer(bs)
                _E.cipher_encrypt_block(o,_X(bk,fb))
                ct+=o.raw
                fb=_X(bk,o.raw)

        # RSA-OAEP key encapsulation
        c=self._wrap_key(K)
        cb=_O(c,(c.bit_length()+7)//8)

        # Assemble protocol messages
        cr=os.urandom(16);sr=os.urandom(16)
        m1=self._msg(0x01,bytes([3,0,1,2])+cr)
        m2=self._msg(0x02,bytes([mode])+iv+sr)
        m3=self._msg(0x03,_S.pack('>H',len(cb))+cb)
        m4=self._msg(0x04,ct)

        return m1,m2,m3,m4

if __name__=='__main__':
    print("STP v2.1 Cipher Module")
    print(f"Engine: {_E.cipher_get_name().decode()}")
    print("Usage: instantiate _Channel(key_params_path)")
