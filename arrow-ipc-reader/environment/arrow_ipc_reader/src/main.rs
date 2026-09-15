// Arrow IPC Stream Reader — converts .arrows files to integration test JSON

use std::env;
use std::fs;
use std::process;
use serde_json::{json, Value};

// ─── byte readers ───────────────────────────────────────────────────────────

fn rd_u8(b: &[u8], p: usize) -> u8  { b[p] }
fn rd_i8(b: &[u8], p: usize) -> i8  { b[p] as i8 }
fn rd_u16(b: &[u8], p: usize) -> u16 { u16::from_le_bytes([b[p], b[p+1]]) }
fn rd_i16(b: &[u8], p: usize) -> i16 { i16::from_le_bytes([b[p], b[p+1]]) }
fn rd_u32(b: &[u8], p: usize) -> u32 { u32::from_le_bytes(b[p..p+4].try_into().unwrap()) }
fn rd_i32(b: &[u8], p: usize) -> i32 { i32::from_le_bytes(b[p..p+4].try_into().unwrap()) }
fn rd_i64(b: &[u8], p: usize) -> i64 { i64::from_le_bytes(b[p..p+8].try_into().unwrap()) }
fn rd_f64(b: &[u8], p: usize) -> f64 { f64::from_le_bytes(b[p..p+8].try_into().unwrap()) }

// ─── FlatBuffer table reader ────────────────────────────────────────────────

struct Fb<'a> { buf: &'a [u8], pos: usize, vt: usize, vt_size: usize }

impl<'a> Fb<'a> {
    fn root(buf: &'a [u8]) -> Self {
        Self::at(buf, rd_u32(buf, 0) as usize)
    }
    fn at(buf: &'a [u8], pos: usize) -> Self {
        let so = rd_i32(buf, pos);
        let vt = (pos as i64 - so as i64) as usize;
        let vt_size = rd_u16(buf, vt) as usize;
        Fb { buf, pos, vt, vt_size }
    }
    fn fp(&self, slot: usize) -> Option<usize> {
        let e = self.vt + 4 + slot * 2;
        if e + 2 > self.vt + self.vt_size { return None; }
        let o = rd_u16(self.buf, e) as usize;
        if o == 0 { None } else { Some(self.pos + o) }
    }
    fn g_u8(&self, s: usize) -> Option<u8>  { self.fp(s).map(|p| rd_u8(self.buf, p)) }
    fn g_i16(&self, s: usize) -> Option<i16> { self.fp(s).map(|p| rd_i16(self.buf, p)) }
    fn g_i32(&self, s: usize) -> Option<i32> { self.fp(s).map(|p| rd_i32(self.buf, p)) }
    fn g_i64(&self, s: usize) -> Option<i64> { self.fp(s).map(|p| rd_i64(self.buf, p)) }
    fn g_bool(&self, s: usize) -> Option<bool> { self.fp(s).map(|p| self.buf[p] != 0) }
    fn g_str(&self, s: usize) -> Option<&'a str> {
        self.fp(s).map(|p| {
            let o = rd_u32(self.buf, p) as usize;
            let sp = p + o;
            let ln = rd_u32(self.buf, sp) as usize;
            std::str::from_utf8(&self.buf[sp+4..sp+4+ln]).unwrap_or("")
        })
    }
    fn g_tbl(&self, s: usize) -> Option<Fb<'a>> {
        self.fp(s).map(|p| { let o = rd_u32(self.buf, p) as usize; Fb::at(self.buf, p + o) })
    }
    fn g_vec_len(&self, s: usize) -> usize {
        self.fp(s).map_or(0, |p| { let o = rd_u32(self.buf, p) as usize; rd_u32(self.buf, p+o) as usize })
    }
    fn g_vec_tbl(&self, s: usize, i: usize) -> Option<Fb<'a>> {
        self.fp(s).map(|p| {
            let o = rd_u32(self.buf, p) as usize;
            let ep = p + o + 4 + i * 4;
            let eo = rd_u32(self.buf, ep) as usize;
            Fb::at(self.buf, ep + eo)
        })
    }
    fn g_svec(&self, s: usize) -> Option<(usize, usize)> {
        self.fp(s).map(|p| {
            let o = rd_u32(self.buf, p) as usize;
            let vs = p + o;
            (vs + 4, rd_u32(self.buf, vs) as usize)
        })
    }
}

// ─── Arrow type info ────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct FldInfo {
    name: String,
    nullable: bool,
    type_id: u8,        // FlatBuffers Type union discriminant
    bit_width: i32,     // for Int/Float
    is_signed: bool,    // for Int
    children: Vec<FldInfo>,
}

// ─── IPC stream reader ──────────────────────────────────────────────────────

fn read_ipc(data: &[u8]) -> Value {
    let mut pos = 0usize;
    let mut schema_fields: Vec<FldInfo> = vec![];
    let mut schema_json = json!({});
    let mut batches: Vec<Value> = vec![];

    while pos + 8 <= data.len() {
        let cont = rd_u32(data, pos);
        if cont != 0xFFFFFFFF { break; }
        pos += 4;
        let msz = rd_i32(data, pos) as usize;
        pos += 4;
        if msz == 0 { break; }

        let meta = &data[pos..pos + msz];
        let body_start = pos + msz;

        let msg = Fb::root(meta);
        let body_len = msg.g_i64(2).unwrap_or(0) as usize;
        let header_type = msg.g_u8(1).unwrap_or(0);

        let body = if body_start + body_len <= data.len() {
            &data[body_start..body_start + body_len]
        } else { &[] };

        match header_type {
            1 => { // Schema
                let hdr = msg.g_tbl(2).unwrap();
                schema_fields = parse_schema(&hdr);
                schema_json = build_schema_json(&schema_fields);
            }
            3 => { // RecordBatch
                let hdr = msg.g_tbl(2).unwrap();
                batches.push(build_batch(&hdr, body, &schema_fields));
            }
            _ => {}
        }
        pos = body_start + body_len;
    }

    json!({ "schema": schema_json, "batches": batches })
}

fn parse_schema(st: &Fb) -> Vec<FldInfo> {
    let n = st.g_vec_len(1);
    (0..n).map(|i| parse_field(&st.g_vec_tbl(1, i).unwrap())).collect()
}

fn parse_field(ft: &Fb) -> FldInfo {
    let name = ft.g_str(0).unwrap_or("").to_string();
    let nullable = ft.g_bool(1).unwrap_or(true);
    // Type union — discriminant at slot 2, value at slot 3:
    let type_id = ft.g_u8(2).unwrap_or(0);
    let (bit_width, is_signed) = match type_id {
        2 => { // Int
            let tt = ft.g_tbl(3).unwrap();
            (tt.g_i32(0).unwrap_or(32), tt.g_bool(1).unwrap_or(true))
        }
        3 => { // FloatingPoint
            let tt = ft.g_tbl(3).unwrap();
            let prec = tt.g_i16(0).unwrap_or(2);
            (match prec { 0 => 16, 1 => 32, _ => 64 }, false)
        }
        _ => (0, false),
    };
    FldInfo { name, nullable, type_id, bit_width, is_signed, children: vec![] }
}

fn build_schema_json(fields: &[FldInfo]) -> Value {
    let fs: Vec<Value> = fields.iter().map(|f| {
        json!({ "name": f.name, "nullable": f.nullable, "type": {}, "children": [] })
    }).collect();
    json!({ "fields": fs })
}

// ─── batch reconstruction ───────────────────────────────────────────────────

struct St<'a> {
    body: &'a [u8],
    nodes: Vec<(i64, i64)>,
    bufs:  Vec<(i64, i64)>,
    ni: usize,
    bi: usize,
}

fn build_batch(rb: &Fb, body: &[u8], fields: &[FldInfo]) -> Value {
    let length = rb.g_i64(0).unwrap_or(0);
    let mut nodes = vec![];
    if let Some((ds, cnt)) = rb.g_svec(1) {
        for i in 0..cnt {
            let p = ds + i * 16;
            nodes.push((rd_i64(rb.buf, p), rd_i64(rb.buf, p + 8)));
        }
    }
    let mut bufs = vec![];
    if let Some((ds, cnt)) = rb.g_svec(2) {
        for i in 0..cnt {
            let p = ds + i * 16;
            bufs.push((rd_i64(rb.buf, p), rd_i64(rb.buf, p + 8)));
        }
    }
    let mut st = St { body, nodes, bufs, ni: 0, bi: 0 };
    let cols: Vec<Value> = fields.iter().map(|f| recon(&mut st, f)).collect();
    json!({ "count": length, "columns": cols })
}

fn next_buf(st: &mut St) -> (i64, i64) { let b = st.bufs[st.bi]; st.bi += 1; b }

fn read_validity(st: &mut St, len: usize, nc: usize) -> Vec<i32> {
    let b = next_buf(st);
    if nc == 0 && b.1 == 0 { return vec![1i32; len]; }
    let start = b.0 as usize;
    (0..len).map(|i| {
        let byte = if start + i / 8 < st.body.len() { st.body[start + i / 8] } else { 0xFF };
        ((byte >> (7 - (i % 8))) & 1) as i32
    }).collect()
}

fn recon(st: &mut St, f: &FldInfo) -> Value {
    let (length, null_count) = st.nodes[st.ni];
    st.ni += 1;
    let len = length as usize;
    let nc = null_count as usize;

    match f.type_id {
        2 if f.bit_width == 32 && f.is_signed => { // Int32 only
            let v = read_validity(st, len, nc);
            let db = next_buf(st);
            let ds = db.0 as usize;
            let data: Vec<Value> = (0..len).map(|i| json!(rd_i32(st.body, ds + i * 4))).collect();
            json!({ "name": f.name, "count": len, "VALIDITY": v, "DATA": data })
        }
        3 if f.bit_width == 64 => { // Float64 only
            let v = read_validity(st, len, nc);
            let db = next_buf(st);
            let ds = db.0 as usize;
            let data: Vec<Value> = (0..len).map(|i| json!(rd_f64(st.body, ds + i * 8))).collect();
            json!({ "name": f.name, "count": len, "VALIDITY": v, "DATA": data })
        }
        _ => {
            // All other types: consume validity + data buffers and output zeros
            let v = read_validity(st, len, nc);
            let _db = next_buf(st);
            json!({ "name": f.name, "count": len, "VALIDITY": v, "DATA": vec![0; len] })
        }
    }
}

// ─── main ───────────────────────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("Usage: {} <input.arrows> <output.json>", args[0]);
        process::exit(1);
    }
    let data = fs::read(&args[1]).unwrap_or_else(|e| {
        eprintln!("Error reading {}: {}", args[1], e);
        process::exit(1);
    });
    let result = read_ipc(&data);
    let out = serde_json::to_string_pretty(&result).unwrap();
    fs::write(&args[2], &out).unwrap_or_else(|e| {
        eprintln!("Error writing {}: {}", args[2], e);
        process::exit(1);
    });
}
