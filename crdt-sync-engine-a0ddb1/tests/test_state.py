
import subprocess
import json
import os
import pytest


def run_node(script: str, timeout: int = 30) -> str:
    """Run inline Node.js script in /app, return stdout."""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, timeout=timeout,
        cwd="/app"
    )
    if result.returncode != 0:
        pytest.fail(
            f"Node.js error (exit {result.returncode}):\n"
            f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
        )
    return result.stdout.strip()


@pytest.fixture(scope="session", autouse=True)
def compile_project():
    """Compile TypeScript if dist/ doesn't exist yet."""
    if not os.path.isdir("/app/dist"):
        r = subprocess.run(
            ["npm", "install"], cwd="/app",
            capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, f"npm install failed: {r.stderr}"
        r = subprocess.run(
            ["npx", "tsc"], cwd="/app",
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, (
            f"tsc failed: {r.stderr}\n{r.stdout}"
        )


# ─── Encoding: varUint ───────────────────────────────────────────────

class TestVarUintEncoding:
    def test_roundtrip_basic(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const v=[0,1,127,128,255,256,16383,16384,100000,2147483647];
const e=new Encoder(); v.forEach(x=>e.writeVarUint(x));
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(v.map(()=>d.readVarUint())));
""")
        assert json.loads(out) == [0,1,127,128,255,256,16383,16384,100000,2147483647]

    def test_single_byte_boundary(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const e=new Encoder(); e.writeVarUint(127);
const b=e.toUint8Array();
console.log(JSON.stringify({len:b.length,b0:b[0]}));
""")
        d = json.loads(out)
        assert d["len"] == 1
        assert d["b0"] == 0x7F

    def test_two_byte_boundary(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const e=new Encoder(); e.writeVarUint(128);
const b=e.toUint8Array();
console.log(JSON.stringify({len:b.length,b0:b[0],b1:b[1]}));
""")
        d = json.loads(out)
        assert d["len"] == 2
        assert d["b0"] == 0x80
        assert d["b1"] == 0x01

    def test_large_value(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const e=new Encoder(); e.writeVarUint(4294967295);
const d=new Decoder(e.toUint8Array());
console.log(d.readVarUint());
""")
        assert int(out) == 4294967295


# ─── Encoding: varInt ─────────────────────────────────────────────────

class TestVarIntEncoding:
    def test_roundtrip(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const v=[0,1,-1,63,-63,64,-64,8191,-8191,100000,-100000];
const e=new Encoder(); v.forEach(x=>e.writeVarInt(x));
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(v.map(()=>d.readVarInt())));
""")
        assert json.loads(out) == [0,1,-1,63,-63,64,-64,8191,-8191,100000,-100000]

    def test_sign_bit(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const e=new Encoder(); e.writeVarInt(-1);
const b=e.toUint8Array();
console.log(JSON.stringify({b0:b[0]}));
""")
        d = json.loads(out)
        assert (d["b0"] & 0x40) != 0  # sign bit set

    def test_positive_no_sign(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const e=new Encoder(); e.writeVarInt(1);
const b=e.toUint8Array();
console.log(JSON.stringify({b0:b[0]}));
""")
        d = json.loads(out)
        assert (d["b0"] & 0x40) == 0  # sign bit not set


# ─── Encoding: varString ─────────────────────────────────────────────

class TestVarStringEncoding:
    def test_roundtrip(self):
        out = run_node(r"""
const {Encoder,Decoder}=require('./dist/encoding');
const v=["","hello","hello world 123","unicode: \u00f1 \u4f60\u597d"];
const e=new Encoder(); v.forEach(x=>e.writeVarString(x));
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(v.map(()=>d.readVarString())));
""")
        expected = ["", "hello", "hello world 123", "unicode: \u00f1 \u4f60\u597d"]
        assert json.loads(out) == expected

    def test_long_string(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const s='a'.repeat(1000);
const e=new Encoder(); e.writeVarString(s);
const d=new Decoder(e.toUint8Array());
console.log(d.readVarString().length);
""")
        assert int(out) == 1000


# ─── Encoding: writeAny / readAny ────────────────────────────────────

class TestAnyEncoding:
    def test_primitives(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const v=[null,42,-7,true,false,"hello"];
const e=new Encoder(); v.forEach(x=>e.writeAny(x));
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(v.map(()=>d.readAny())));
""")
        assert json.loads(out) == [None, 42, -7, True, False, "hello"]

    def test_undefined(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const e=new Encoder(); e.writeAny(undefined);
const d=new Decoder(e.toUint8Array());
const r=d.readAny();
console.log(r === undefined ? "UNDEF" : "WRONG");
""")
        assert out == "UNDEF"

    def test_nested_object(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const obj={a:1,b:"two",c:[3,4],d:{e:true}};
const e=new Encoder(); e.writeAny(obj);
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(d.readAny()));
""")
        assert json.loads(out) == {"a":1,"b":"two","c":[3,4],"d":{"e":True}}

    def test_uint8array(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const arr=new Uint8Array([1,2,3,255]);
const e=new Encoder(); e.writeAny(arr);
const d=new Decoder(e.toUint8Array());
const r=d.readAny();
console.log(JSON.stringify(Array.from(r)));
""")
        assert json.loads(out) == [1,2,3,255]

    def test_float(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const e=new Encoder(); e.writeAny(3.14);
const d=new Decoder(e.toUint8Array());
const r=d.readAny();
console.log(Math.abs(r - 3.14) < 1e-10 ? "OK" : "FAIL");
""")
        assert out == "OK"

    def test_empty_array(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const e=new Encoder(); e.writeAny([]);
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(d.readAny()));
""")
        assert json.loads(out) == []

    def test_empty_object(self):
        out = run_node("""
const {Encoder,Decoder}=require('./dist/encoding');
const e=new Encoder(); e.writeAny({});
const d=new Decoder(e.toUint8Array());
console.log(JSON.stringify(d.readAny()));
""")
        assert json.loads(out) == {}


# ─── Byte-level reference vector compatibility ───────────────────────

class TestByteCompatibility:
    """Verify byte-level output matches lib0 reference vectors."""

    def test_varuint_reference_vectors(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const cases=[
    [0,"00"],[1,"01"],[127,"7f"],[128,"8001"],
    [255,"ff01"],[256,"8002"],[16383,"ff7f"],
    [16384,"808001"],[2097151,"ffff7f"]
];
const r=cases.map(([v,exp])=>{
    const e=new Encoder();e.writeVarUint(v);
    const hex=Buffer.from(e.toUint8Array()).toString('hex');
    return {v,exp,hex,ok:hex===exp};
});
console.log(JSON.stringify(r));
""")
        results = json.loads(out)
        for r in results:
            assert r["ok"], f"writeVarUint({r['v']}): expected {r['exp']}, got {r['hex']}"

    def test_varint_reference_vectors(self):
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const cases=[
    [0,"00"],[1,"01"],[-1,"41"],[63,"3f"],[-63,"7f"],
    [64,"8001"],[-64,"c001"],[8191,"bf7f"],[-8191,"ff7f"]
];
const r=cases.map(([v,exp])=>{
    const e=new Encoder();e.writeVarInt(v);
    const hex=Buffer.from(e.toUint8Array()).toString('hex');
    return {v,exp,hex,ok:hex===exp};
});
console.log(JSON.stringify(r));
""")
        results = json.loads(out)
        for r in results:
            assert r["ok"], f"writeVarInt({r['v']}): expected {r['exp']}, got {r['hex']}"

    def test_writeany_reference_vectors(self):
        """Non-float writeAny must produce exact lib0-compatible bytes."""
        out = run_node("""
const {Encoder}=require('./dist/encoding');
const cases=[
    ["null",null,"7e"],
    ["int42",42,"7d2a"],
    ["int-7",-7,"7d47"],
    ["true",true,"78"],
    ["false",false,"79"],
    ["emptyStr","","7700"],
    ["hi","hi","77026869"],
    ["emptyObj",{},"7600"],
    ["emptyArr",[],"7500"]
];
const r=cases.map(([label,v,exp])=>{
    const e=new Encoder();e.writeAny(v);
    const hex=Buffer.from(e.toUint8Array()).toString('hex');
    return {label,exp,hex,ok:hex===exp};
});
// undefined must be tested separately (JSON.parse loses it)
const eu=new Encoder();eu.writeAny(undefined);
const uhex=Buffer.from(eu.toUint8Array()).toString('hex');
r.push({label:"undefined",exp:"7f",hex:uhex,ok:uhex==="7f"});
console.log(JSON.stringify(r));
""")
        results = json.loads(out)
        for r in results:
            assert r["ok"], f"writeAny({r['label']}): expected {r['exp']}, got {r['hex']}"


# ─── Float32 decoder compatibility ──────────────────────────────────

class TestFloat32Decode:
    def test_decode_float32_tag(self):
        """Decoder must handle lib0's float32 type tag (124)."""
        out = run_node("""
const {Decoder}=require('./dist/encoding');
// Construct a float32-tagged value manually: tag 124 + 4 bytes big-endian
const buf=new Uint8Array(5);
buf[0]=124;
const dv=new DataView(buf.buffer);
dv.setFloat32(1,1.5,false);
const d=new Decoder(buf);
const result=d.readAny();
console.log(JSON.stringify({val:result,match:result===1.5}));
""")
        d = json.loads(out)
        assert d["match"] is True, f"Expected 1.5, got {d['val']}"

    def test_decode_float32_negative(self):
        """Decoder handles negative float32 values."""
        out = run_node("""
const {Decoder}=require('./dist/encoding');
const buf=new Uint8Array(5);
buf[0]=124;
const dv=new DataView(buf.buffer);
dv.setFloat32(1,-42.0,false);
const d=new Decoder(buf);
const result=d.readAny();
console.log(JSON.stringify({val:result,match:result===-42}));
""")
        d = json.loads(out)
        assert d["match"] is True


# ─── State Vector ─────────────────────────────────────────────────────

class TestStateVector:
    def test_roundtrip(self):
        out = run_node("""
const {encodeStateVector,decodeStateVector}=require('./dist/update');
const sv=new Map([[100,5],[200,10],[300,1]]);
const enc=encodeStateVector(sv);
const dec=decodeStateVector(enc);
const r={}; for(const[k,v]of dec)r[k]=v;
console.log(JSON.stringify(r));
""")
        assert json.loads(out) == {"100":5,"200":10,"300":1}

    def test_empty(self):
        out = run_node("""
const {encodeStateVector,decodeStateVector}=require('./dist/update');
const enc=encodeStateVector(new Map());
const dec=decodeStateVector(enc);
console.log(dec.size);
""")
        assert int(out) == 0


# ─── Document: Map Operations ────────────────────────────────────────

class TestDocumentMap:
    def test_set_get(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(1);
d.mapSet("t","x",42); d.mapSet("t","y","hello");
console.log(JSON.stringify({x:d.mapGet("t","x"),y:d.mapGet("t","y")}));
""")
        assert json.loads(out) == {"x":42,"y":"hello"}

    def test_overwrite(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(1);
d.mapSet("t","x",1); d.mapSet("t","x",2); d.mapSet("t","x",3);
console.log(d.mapGet("t","x"));
""")
        assert int(out) == 3

    def test_delete(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(1);
d.mapSet("t","x",42); d.mapDelete("t","x");
console.log(d.mapGet("t","x") === undefined ? "UNDEF" : "WRONG");
""")
        assert out == "UNDEF"

    def test_entries(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(1);
d.mapSet("t","a",1); d.mapSet("t","b",2); d.mapSet("t","c",3);
d.mapDelete("t","b");
const r={}; for(const[k,v]of d.mapEntries("t"))r[k]=v;
console.log(JSON.stringify(r));
""")
        assert json.loads(out) == {"a":1,"c":3}

    def test_state_vector(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(42);
d.mapSet("t","x",1); d.mapSet("t","y",2); d.mapSet("t","z",3);
const sv=d.getStateVector();
const r={}; for(const[k,v]of sv)r[k]=v;
console.log(JSON.stringify(r));
""")
        assert json.loads(out) == {"42":3}

    def test_nonexistent_key(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const d=new Doc(1);
console.log(d.mapGet("t","nope") === undefined ? "UNDEF" : "WRONG");
""")
        assert out == "UNDEF"


# ─── Sync: Basic ─────────────────────────────────────────────────────

class TestSync:
    def test_no_conflict(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(1), b=new Doc(2);
a.mapSet("m","x",1); a.mapSet("m","y",2);
b.mapSet("m","z",3); b.mapSet("m","w",4);
syncPair(a,b);
const ae={}, be={};
for(const[k,v]of a.mapEntries("m"))ae[k]=v;
for(const[k,v]of b.mapEntries("m"))be[k]=v;
console.log(JSON.stringify({a:ae,b:be}));
""")
        d = json.loads(out)
        exp = {"x":1,"y":2,"z":3,"w":4}
        assert d["a"] == exp
        assert d["b"] == exp

    def test_conflict_resolution(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(1), b=new Doc(2);
a.mapSet("m","key","from_a");
b.mapSet("m","key","from_b");
syncPair(a,b);
console.log(JSON.stringify({a:a.mapGet("m","key"),b:b.mapGet("m","key")}));
""")
        d = json.loads(out)
        assert d["a"] == "from_b"
        assert d["b"] == "from_b"

    def test_delete_sync(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(1), b=new Doc(2);
a.mapSet("m","x",1); a.mapSet("m","y",2);
syncPair(a,b);
a.mapDelete("m","x");
syncPair(a,b);
console.log(b.mapGet("m","x") === undefined ? "UNDEF" : "WRONG");
""")
        assert out == "UNDEF"

    def test_concurrent_set_delete(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(1), b=new Doc(2);
a.mapSet("m","k","initial");
syncPair(a,b);
a.mapDelete("m","k");
b.mapSet("m","k","new_value");
syncPair(a,b);
console.log(JSON.stringify({a:a.mapGet("m","k"),b:b.mapGet("m","k")}));
""")
        d = json.loads(out)
        assert d["a"] == "new_value"
        assert d["b"] == "new_value"

    def test_multiple_maps(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(1), b=new Doc(2);
a.mapSet("users","alice",100); a.mapSet("items","sword",50);
b.mapSet("users","bob",200); b.mapSet("items","shield",75);
syncPair(a,b);
const au={},bu={},ai={},bi={};
for(const[k,v]of a.mapEntries("users"))au[k]=v;
for(const[k,v]of b.mapEntries("users"))bu[k]=v;
for(const[k,v]of a.mapEntries("items"))ai[k]=v;
for(const[k,v]of b.mapEntries("items"))bi[k]=v;
console.log(JSON.stringify({au,bu,ai,bi}));
""")
        d = json.loads(out)
        assert d["au"] == d["bu"] == {"alice":100,"bob":200}
        assert d["ai"] == d["bi"] == {"sword":50,"shield":75}


# ─── Update Encoding ─────────────────────────────────────────────────

class TestUpdateEncoding:
    def test_encode_decode_roundtrip(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {encodeUpdate,decodeUpdate}=require('./dist/update');
const d=new Doc(1);
d.mapSet("m","a",1); d.mapSet("m","b","hello"); d.mapSet("m","c",true);
const u=d.computeUpdateSince(new Map());
const enc=encodeUpdate(u);
const dec=decodeUpdate(enc);
const d2=new Doc(2); d2.applyUpdate(dec);
const r={}; for(const[k,v]of d2.mapEntries("m"))r[k]=v;
console.log(JSON.stringify(r));
""")
        assert json.loads(out) == {"a":1,"b":"hello","c":True}

    def test_delete_set_encoding(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {encodeUpdate,decodeUpdate}=require('./dist/update');
const d=new Doc(1);
d.mapSet("m","a",1); d.mapSet("m","b",2);
d.mapDelete("m","a");
const u=d.computeUpdateSince(new Map());
const enc=encodeUpdate(u);
const dec=decodeUpdate(enc);
const d2=new Doc(2); d2.applyUpdate(dec);
const r={}; for(const[k,v]of d2.mapEntries("m"))r[k]=v;
console.log(JSON.stringify(r));
""")
        assert json.loads(out) == {"b":2}


# ─── Merge Updates ────────────────────────────────────────────────────

class TestMergeUpdates:
    def test_merge_equivalence(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {encodeUpdate,decodeUpdate,mergeUpdates}=require('./dist/update');
const d1=new Doc(1);
d1.mapSet("m","a",1); d1.mapSet("m","b",2);
const u1=encodeUpdate(d1.computeUpdateSince(new Map()));
const d2=new Doc(2);
d2.mapSet("m","c",3); d2.mapSet("m","d",4);
const u2=encodeUpdate(d2.computeUpdateSince(new Map()));
const seqD=new Doc(100);
seqD.applyUpdate(decodeUpdate(u1));
seqD.applyUpdate(decodeUpdate(u2));
const merged=mergeUpdates([u1,u2]);
const mergeD=new Doc(101);
mergeD.applyUpdate(decodeUpdate(merged));
const se={},me={};
for(const[k,v]of seqD.mapEntries("m"))se[k]=v;
for(const[k,v]of mergeD.mapEntries("m"))me[k]=v;
console.log(JSON.stringify({eq:JSON.stringify(se)===JSON.stringify(me),se,me}));
""")
        d = json.loads(out)
        assert d["eq"] is True
        assert d["se"] == {"a":1,"b":2,"c":3,"d":4}

    def test_merge_with_overlap(self):
        """Merging updates that share some items should deduplicate."""
        out = run_node("""
const {Doc}=require('./dist/document');
const {encodeUpdate,decodeUpdate,mergeUpdates}=require('./dist/update');
const d1=new Doc(1);
d1.mapSet("m","x",10); d1.mapSet("m","y",20);
const full=encodeUpdate(d1.computeUpdateSince(new Map()));
const sv1=new Map([[1,1]]);
const partial=encodeUpdate(d1.computeUpdateSince(sv1));
const merged=mergeUpdates([full,partial]);
const r=new Doc(99);
r.applyUpdate(decodeUpdate(merged));
const e={}; for(const[k,v]of r.mapEntries("m"))e[k]=v;
console.log(JSON.stringify(e));
""")
        assert json.loads(out) == {"x":10,"y":20}


# ─── Convergence ──────────────────────────────────────────────────────

class TestConvergence:
    def test_five_doc_convergence(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncAll}=require('./dist/sync');
function mulberry32(s){return function(){let t=s+=0x6D2B79F5;
t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);
return((t^t>>>14)>>>0)/4294967296;}}
const rng=mulberry32(42);
const ri=(a,b)=>Math.floor(rng()*(b-a+1))+a;
const docs=[new Doc(10),new Doc(20),new Doc(30),new Doc(40),new Doc(50)];
const keys=['alpha','beta','gamma','delta','epsilon','zeta','eta','theta'];
for(const doc of docs){
  for(let i=0;i<50;i++){
    const k=keys[ri(0,keys.length-1)];
    if(rng()<0.2)doc.mapDelete("data",k);
    else doc.mapSet("data",k,ri(0,1000));
  }
}
syncAll(docs);
const results=docs.map(d=>{
  const e={}; for(const[k,v]of d.mapEntries("data"))e[k]=v;
  return JSON.stringify(e,Object.keys(e).sort());
});
console.log(JSON.stringify({converged:results.every(r=>r===results[0])}));
""", timeout=60)
        assert json.loads(out)["converged"] is True

    def test_three_way_conflict(self):
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncAll}=require('./dist/sync');
const a=new Doc(1),b=new Doc(2),c=new Doc(3);
a.mapSet("m","key","val_a");
b.mapSet("m","key","val_b");
c.mapSet("m","key","val_c");
syncAll([a,b,c]);
console.log(JSON.stringify({
  a:a.mapGet("m","key"),b:b.mapGet("m","key"),c:c.mapGet("m","key")
}));
""")
        d = json.loads(out)
        assert d["a"] == "val_c"
        assert d["b"] == "val_c"
        assert d["c"] == "val_c"

    def test_incremental_sync(self):
        """Partial syncs during operation, then full sync — must converge."""
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair,syncAll}=require('./dist/sync');
function mulberry32(s){return function(){let t=s+=0x6D2B79F5;
t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);
return((t^t>>>14)>>>0)/4294967296;}}
const rng=mulberry32(99);
const ri=(a,b)=>Math.floor(rng()*(b-a+1))+a;
const docs=[new Doc(10),new Doc(20),new Doc(30)];
const keys=['a','b','c','d','e'];
for(let round=0;round<5;round++){
  for(const doc of docs){
    for(let i=0;i<10;i++){
      const k=keys[ri(0,keys.length-1)];
      if(rng()<0.15)doc.mapDelete("m",k);
      else doc.mapSet("m",k,ri(0,500));
    }
  }
  const i=ri(0,2),j=(i+1)%3;
  syncPair(docs[i],docs[j]);
}
syncAll(docs);
const results=docs.map(d=>{
  const e={}; for(const[k,v]of d.mapEntries("m"))e[k]=v;
  return JSON.stringify(e,Object.keys(e).sort());
});
console.log(JSON.stringify({converged:results.every(r=>r===results[0])}));
""", timeout=60)
        assert json.loads(out)["converged"] is True

    def test_high_clock_conflict(self):
        """When clocks differ, higher clock wins regardless of clientID."""
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncPair}=require('./dist/sync');
const a=new Doc(999), b=new Doc(1);
a.mapSet("m","k","a1");
b.mapSet("m","k","b1"); b.mapSet("m","k","b2"); b.mapSet("m","k","b3");
syncPair(a,b);
console.log(JSON.stringify({
  a:a.mapGet("m","k"),b:b.mapGet("m","k")
}));
""")
        d = json.loads(out)
        assert d["a"] == "b3"
        assert d["b"] == "b3"

    def test_many_writers_same_key(self):
        """Many replicas writing same key must converge deterministically."""
        out = run_node("""
const {Doc}=require('./dist/document');
const {syncAll}=require('./dist/sync');
const docs=[new Doc(5),new Doc(3),new Doc(7),new Doc(1),new Doc(4)];
docs.forEach(d=>d.mapSet("m","conflict","val_from_"+d.clientID));
syncAll(docs);
const results=docs.map(d=>d.mapGet("m","conflict"));
console.log(JSON.stringify({
  allSame:results.every(r=>r===results[0]),
  winner:results[0]
}));
""", timeout=30)
        d = json.loads(out)
        assert d["allSame"] is True
        assert d["winner"] == "val_from_7"


# ─── CLI Tool ─────────────────────────────────────────────────────────

class TestCli:
    def test_cli_direct_execution(self):
        """CLI must work when invoked directly via subprocess."""
        result = subprocess.run(
            ["node", "dist/cli.js", "encode-sv", '{"1":5,"2":10}'],
            capture_output=True, text=True, cwd="/app", timeout=10
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        hex_out = result.stdout.strip()
        result2 = subprocess.run(
            ["node", "dist/cli.js", "decode-sv", hex_out],
            capture_output=True, text=True, cwd="/app", timeout=10
        )
        assert result2.returncode == 0, f"CLI decode failed: {result2.stderr}"
        decoded = json.loads(result2.stdout.strip())
        assert decoded == {"1": 5, "2": 10}

    def test_roundtrip_any_via_cli(self):
        """roundtrip-any must encode then decode correctly."""
        out = run_node("""
const {runCli}=require('./dist/cli');
const r=runCli(['roundtrip-any','{"a":1,"b":"hello","c":[true,null]}']);
console.log(r);
""")
        assert json.loads(out) == {"a": 1, "b": "hello", "c": [True, None]}

    def test_simulate_basic(self):
        """simulate must handle set + sync ops correctly."""
        out = run_node("""
const {runCli}=require('./dist/cli');
const scenario={
  docs:[1,2],
  ops:[
    {doc:1,op:"set",map:"m",key:"a",value:10},
    {doc:2,op:"set",map:"m",key:"b",value:20},
    {op:"sync"}
  ]
};
console.log(runCli(['simulate',JSON.stringify(scenario)]));
""")
        d = json.loads(out)
        assert d["1"]["m"] == {"a": 10, "b": 20}
        assert d["2"]["m"] == {"a": 10, "b": 20}

    def test_simulate_partial_sync(self):
        """simulate must support sync_pair and delete ops."""
        out = run_node("""
const {runCli}=require('./dist/cli');
const scenario={
  docs:[1,2,3],
  ops:[
    {doc:1,op:"set",map:"m",key:"x",value:100},
    {doc:2,op:"set",map:"m",key:"y",value:200},
    {op:"sync_pair",docs:[1,2]},
    {doc:3,op:"set",map:"m",key:"z",value:300},
    {doc:1,op:"delete",map:"m",key:"x"},
    {op:"sync"}
  ]
};
const result=JSON.parse(runCli(['simulate',JSON.stringify(scenario)]));
console.log(JSON.stringify(result));
""")
        d = json.loads(out)
        # After sync_all: doc 1 deleted "x", all should have y=200, z=300
        for doc_id in ["1", "2", "3"]:
            assert "x" not in d[doc_id]["m"], f"doc {doc_id} should not have 'x'"
            assert d[doc_id]["m"]["y"] == 200
            assert d[doc_id]["m"]["z"] == 300

    def test_simulate_conflict_via_cli(self):
        """simulate with conflicting writes must converge deterministically."""
        out = run_node("""
const {runCli}=require('./dist/cli');
const scenario={
  docs:[10,20,30],
  ops:[
    {doc:10,op:"set",map:"s",key:"winner",value:"ten"},
    {doc:20,op:"set",map:"s",key:"winner",value:"twenty"},
    {doc:30,op:"set",map:"s",key:"winner",value:"thirty"},
    {op:"sync"}
  ]
};
const result=JSON.parse(runCli(['simulate',JSON.stringify(scenario)]));
console.log(JSON.stringify(result));
""")
        d = json.loads(out)
        # Highest clientID (30) should win (same clock=0, higher clientID wins)
        for doc_id in ["10", "20", "30"]:
            assert d[doc_id]["s"]["winner"] == "thirty"
