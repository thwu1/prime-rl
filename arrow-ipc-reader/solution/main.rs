// Arrow IPC Stream Reader — converts .arrows files to integration test JSON

use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::process;

// ─── byte readers ───────────────────────────────────────────────────────────

fn rd_u8(b: &[u8], p: usize) -> u8 { b[p] }
fn rd_i8(b: &[u8], p: usize) -> i8 { b[p] as i8 }
fn rd_u16(b: &[u8], p: usize) -> u16 { u16::from_le_bytes([b[p], b[p + 1]]) }
fn rd_i16(b: &[u8], p: usize) -> i16 { i16::from_le_bytes([b[p], b[p + 1]]) }
fn rd_u32(b: &[u8], p: usize) -> u32 { u32::from_le_bytes(b[p..p + 4].try_into().unwrap()) }
fn rd_i32(b: &[u8], p: usize) -> i32 { i32::from_le_bytes(b[p..p + 4].try_into().unwrap()) }
fn rd_u64(b: &[u8], p: usize) -> u64 { u64::from_le_bytes(b[p..p + 8].try_into().unwrap()) }
fn rd_i64(b: &[u8], p: usize) -> i64 { i64::from_le_bytes(b[p..p + 8].try_into().unwrap()) }
fn rd_f32(b: &[u8], p: usize) -> f32 { f32::from_le_bytes(b[p..p + 4].try_into().unwrap()) }
fn rd_f64(b: &[u8], p: usize) -> f64 { f64::from_le_bytes(b[p..p + 8].try_into().unwrap()) }

// ─── FlatBuffer table reader ────────────────────────────────────────────────

struct Fb<'a> {
    buf: &'a [u8],
    pos: usize,
    vt: usize,
    vt_size: usize,
}

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
        if e + 2 > self.vt + self.vt_size {
            return None;
        }
        let o = rd_u16(self.buf, e) as usize;
        if o == 0 { None } else { Some(self.pos + o) }
    }
    fn g_u8(&self, s: usize) -> Option<u8> { self.fp(s).map(|p| rd_u8(self.buf, p)) }
    fn g_i16(&self, s: usize) -> Option<i16> { self.fp(s).map(|p| rd_i16(self.buf, p)) }
    fn g_i32(&self, s: usize) -> Option<i32> { self.fp(s).map(|p| rd_i32(self.buf, p)) }
    fn g_i64(&self, s: usize) -> Option<i64> { self.fp(s).map(|p| rd_i64(self.buf, p)) }
    fn g_bool(&self, s: usize) -> Option<bool> { self.fp(s).map(|p| self.buf[p] != 0) }
    fn g_str(&self, s: usize) -> Option<&'a str> {
        self.fp(s).map(|p| {
            let o = rd_u32(self.buf, p) as usize;
            let sp = p + o;
            let ln = rd_u32(self.buf, sp) as usize;
            std::str::from_utf8(&self.buf[sp + 4..sp + 4 + ln]).unwrap_or("")
        })
    }
    fn g_tbl(&self, s: usize) -> Option<Fb<'a>> {
        self.fp(s).map(|p| {
            let o = rd_u32(self.buf, p) as usize;
            Fb::at(self.buf, p + o)
        })
    }
    fn g_vec_len(&self, s: usize) -> usize {
        self.fp(s).map_or(0, |p| {
            let o = rd_u32(self.buf, p) as usize;
            rd_u32(self.buf, p + o) as usize
        })
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
    type_id: u8,
    bit_width: i32,
    is_signed: bool,
    children: Vec<FldInfo>,
    dict_id: Option<i64>,
    dict_index_bit_width: i32,
    dict_index_signed: bool,
}

impl FldInfo {
    fn new() -> Self {
        FldInfo {
            name: String::new(),
            nullable: true,
            type_id: 0,
            bit_width: 0,
            is_signed: false,
            children: vec![],
            dict_id: None,
            dict_index_bit_width: 32,
            dict_index_signed: true,
        }
    }
}

// Type union discriminants from Schema.fbs:
// 0=NONE 1=Null 2=Int 3=FloatingPoint 4=Binary 5=Utf8 6=Bool
// 7=Decimal 8=Date 9=Time 10=Timestamp 11=Interval 12=List
// 13=Struct_ 14=Union 15=FixedSizeBinary 16=FixedSizeList 17=Map
// 18=Duration 19=LargeBinary 20=LargeUtf8 21=LargeList

// ─── IPC stream reader ──────────────────────────────────────────────────────

fn read_ipc(data: &[u8]) -> Value {
    let mut pos = 0usize;
    let mut schema_fields: Vec<FldInfo> = vec![];
    let mut schema_json = json!({});
    let mut batches: Vec<Value> = vec![];
    let mut dicts: Vec<Value> = vec![];
    let mut dict_field_map: HashMap<i64, FldInfo> = HashMap::new();

    while pos + 8 <= data.len() {
        let cont = rd_u32(data, pos);
        if cont != 0xFFFFFFFF {
            break;
        }
        pos += 4;
        let msz = rd_i32(data, pos) as usize;
        pos += 4;
        if msz == 0 {
            break;
        }

        let meta = &data[pos..pos + msz];
        let body_start = pos + msz;

        let msg = Fb::root(meta);
        // Message slots: 0=version(i16), 1=header_type(u8), 2=header(tbl), 3=bodyLength(i64)
        let header_type = msg.g_u8(1).unwrap_or(0);
        let body_len = msg.g_i64(3).unwrap_or(0) as usize;

        let body = if body_start + body_len <= data.len() {
            &data[body_start..body_start + body_len]
        } else {
            &[]
        };

        match header_type {
            1 => {
                // Schema
                let hdr = msg.g_tbl(2).unwrap();
                schema_fields = parse_schema(&hdr);
                schema_json = build_schema_json(&schema_fields);
                collect_dict_fields(&schema_fields, &mut dict_field_map);
            }
            2 => {
                // DictionaryBatch
                let hdr = msg.g_tbl(2).unwrap();
                let dict_id = hdr.g_i64(0).unwrap_or(0);
                if let Some(rb_tbl) = hdr.g_tbl(1) {
                    if let Some(df) = dict_field_map.get(&dict_id) {
                        let val_field = FldInfo {
                            name: format!("DICT{}", dict_id),
                            nullable: true,
                            type_id: df.type_id,
                            bit_width: df.bit_width,
                            is_signed: df.is_signed,
                            children: df.children.clone(),
                            dict_id: None,
                            dict_index_bit_width: 32,
                            dict_index_signed: true,
                        };
                        let d = build_batch(&rb_tbl, body, &[val_field]);
                        dicts.push(json!({"id": dict_id, "data": d}));
                    }
                }
            }
            3 => {
                // RecordBatch
                let hdr = msg.g_tbl(2).unwrap();
                batches.push(build_batch(&hdr, body, &schema_fields));
            }
            _ => {}
        }
        pos = body_start + body_len;
    }

    let mut result = serde_json::Map::new();
    result.insert("schema".into(), schema_json);
    if !dicts.is_empty() {
        result.insert("dictionaries".into(), Value::Array(dicts));
    }
    result.insert("batches".into(), Value::Array(batches));
    Value::Object(result)
}

// ─── schema parsing ─────────────────────────────────────────────────────────

fn parse_schema(st: &Fb) -> Vec<FldInfo> {
    let n = st.g_vec_len(1);
    (0..n)
        .map(|i| parse_field(&st.g_vec_tbl(1, i).unwrap()))
        .collect()
}

fn parse_field(ft: &Fb) -> FldInfo {
    let mut f = FldInfo::new();
    f.name = ft.g_str(0).unwrap_or("").to_string();
    f.nullable = ft.g_bool(1).unwrap_or(true);

    // Type union: slot 2 = discriminant(u8), slot 3 = value(table)
    f.type_id = ft.g_u8(2).unwrap_or(0);
    match f.type_id {
        2 => {
            if let Some(tt) = ft.g_tbl(3) {
                f.bit_width = tt.g_i32(0).unwrap_or(32);
                f.is_signed = tt.g_bool(1).unwrap_or(true);
            }
        }
        3 => {
            if let Some(tt) = ft.g_tbl(3) {
                let prec = tt.g_i16(0).unwrap_or(2);
                f.bit_width = match prec {
                    0 => 16,
                    1 => 32,
                    _ => 64,
                };
            }
        }
        _ => {}
    }

    // Children: slot 5 (slot 4 = dictionary)
    let nc = ft.g_vec_len(5);
    for i in 0..nc {
        f.children.push(parse_field(&ft.g_vec_tbl(5, i).unwrap()));
    }

    // Dictionary encoding: slot 4
    if let Some(dt) = ft.g_tbl(4) {
        f.dict_id = Some(dt.g_i64(0).unwrap_or(0));
        if let Some(idx_tt) = dt.g_tbl(1) {
            f.dict_index_bit_width = idx_tt.g_i32(0).unwrap_or(32);
            f.dict_index_signed = idx_tt.g_bool(1).unwrap_or(true);
        }
    }

    f
}

fn collect_dict_fields(fields: &[FldInfo], map: &mut HashMap<i64, FldInfo>) {
    for f in fields {
        if let Some(id) = f.dict_id {
            map.insert(id, f.clone());
        }
        collect_dict_fields(&f.children, map);
    }
}

// ─── schema JSON output ────────────────────────────────────────────────────

fn build_schema_json(fields: &[FldInfo]) -> Value {
    let fs: Vec<Value> = fields.iter().map(|f| field_json(f)).collect();
    json!({"fields": fs})
}

fn field_json(f: &FldInfo) -> Value {
    let mut m = serde_json::Map::new();
    m.insert("name".into(), json!(f.name));
    m.insert("nullable".into(), json!(f.nullable));
    m.insert("type".into(), type_json(f.type_id, f.bit_width, f.is_signed));
    let ch: Vec<Value> = f.children.iter().map(|c| field_json(c)).collect();
    m.insert("children".into(), Value::Array(ch));
    if let Some(dict_id) = f.dict_id {
        m.insert(
            "dictionary".into(),
            json!({
                "id": dict_id,
                "indexType": type_json(2, f.dict_index_bit_width, f.dict_index_signed),
                "isOrdered": false
            }),
        );
    }
    Value::Object(m)
}

fn type_json(type_id: u8, bw: i32, signed: bool) -> Value {
    match type_id {
        1 => json!({"name": "null"}),
        2 => json!({"name": "int", "bitWidth": bw, "isSigned": signed}),
        3 => {
            let p = match bw {
                16 => "HALF",
                32 => "SINGLE",
                _ => "DOUBLE",
            };
            json!({"name": "floatingpoint", "precision": p})
        }
        4 => json!({"name": "binary"}),
        5 => json!({"name": "utf8"}),
        6 => json!({"name": "bool"}),
        12 => json!({"name": "list"}),
        13 => json!({"name": "struct"}),
        19 => json!({"name": "largebinary"}),
        20 => json!({"name": "largeutf8"}),
        _ => json!({"name": "unknown"}),
    }
}

// ─── batch reconstruction ──────────────────────────────────────────────────

struct St<'a> {
    body: &'a [u8],
    nodes: Vec<(i64, i64)>,
    bufs: Vec<(i64, i64)>,
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
    json!({"count": length, "columns": cols})
}

fn nb(st: &mut St) -> (i64, i64) {
    let b = st.bufs[st.bi];
    st.bi += 1;
    b
}

fn read_val(st: &mut St, len: usize, nc: usize) -> Vec<i32> {
    let b = nb(st);
    if nc == 0 && b.1 == 0 {
        return vec![1i32; len];
    }
    let start = b.0 as usize;
    (0..len)
        .map(|i| {
            let bi = start + i / 8;
            let bit = i % 8;
            let byte = if bi < st.body.len() { st.body[bi] } else { 0xFF };
            // LSB numbering: bit 0 is least significant
            ((byte >> bit) & 1) as i32
        })
        .collect()
}

fn recon(st: &mut St, f: &FldInfo) -> Value {
    // Dictionary-encoded: reconstruct using index type
    if f.dict_id.is_some() {
        let idx_f = FldInfo {
            name: f.name.clone(),
            nullable: f.nullable,
            type_id: 2, // Int
            bit_width: f.dict_index_bit_width,
            is_signed: f.dict_index_signed,
            children: vec![],
            dict_id: None,
            dict_index_bit_width: 32,
            dict_index_signed: true,
        };
        return recon(st, &idx_f);
    }

    let (length, null_count) = st.nodes[st.ni];
    st.ni += 1;
    let len = length as usize;
    let nc = null_count as usize;

    match f.type_id {
        1 => {
            // Null — no buffers
            json!({"name": f.name, "count": len, "VALIDITY": vec![0i32; len]})
        }
        6 => {
            // Bool
            let v = read_val(st, len, nc);
            let db = nb(st);
            let ds = db.0 as usize;
            let data: Vec<i32> = (0..len)
                .map(|i| {
                    let bi = ds + i / 8;
                    if bi < st.body.len() {
                        ((st.body[bi] >> (i % 8)) & 1) as i32
                    } else {
                        0
                    }
                })
                .collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "DATA": data})
        }
        2 => {
            // Int
            let v = read_val(st, len, nc);
            let db = nb(st);
            let ds = db.0 as usize;
            let data: Vec<Value> = (0..len)
                .map(|i| match (f.bit_width, f.is_signed) {
                    (8, true) => json!(rd_i8(st.body, ds + i)),
                    (8, false) => json!(rd_u8(st.body, ds + i)),
                    (16, true) => json!(rd_i16(st.body, ds + i * 2)),
                    (16, false) => json!(rd_u16(st.body, ds + i * 2) as i32),
                    (32, true) => json!(rd_i32(st.body, ds + i * 4)),
                    (32, false) => json!(rd_u32(st.body, ds + i * 4)),
                    (64, true) => json!(rd_i64(st.body, ds + i * 8).to_string()),
                    (64, false) => json!(rd_u64(st.body, ds + i * 8).to_string()),
                    _ => json!(0),
                })
                .collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "DATA": data})
        }
        3 => {
            // FloatingPoint
            let v = read_val(st, len, nc);
            let db = nb(st);
            let ds = db.0 as usize;
            let data: Vec<Value> = (0..len)
                .map(|i| match f.bit_width {
                    32 => json!(rd_f32(st.body, ds + i * 4) as f64),
                    64 => json!(rd_f64(st.body, ds + i * 8)),
                    _ => json!(0.0),
                })
                .collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "DATA": data})
        }
        5 => {
            // Utf8
            let v = read_val(st, len, nc);
            let ob = nb(st);
            let db = nb(st);
            let os = ob.0 as usize;
            let ds = db.0 as usize;

            let offsets: Vec<i32> = (0..=len).map(|i| rd_i32(st.body, os + i * 4)).collect();
            let data: Vec<Value> = (0..len)
                .map(|i| {
                    let s = offsets[i] as usize;
                    let e = offsets[i + 1] as usize;
                    let txt = std::str::from_utf8(&st.body[ds + s..ds + e]).unwrap_or("");
                    json!(txt)
                })
                .collect();
            let oj: Vec<Value> = offsets.iter().map(|o| json!(*o)).collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "OFFSET": oj, "DATA": data})
        }
        4 => {
            // Binary
            let v = read_val(st, len, nc);
            let ob = nb(st);
            let db = nb(st);
            let os = ob.0 as usize;
            let ds = db.0 as usize;

            let offsets: Vec<i32> = (0..=len).map(|i| rd_i32(st.body, os + i * 4)).collect();
            let data: Vec<Value> = (0..len)
                .map(|i| {
                    let s = offsets[i] as usize;
                    let e = offsets[i + 1] as usize;
                    let hex: String = st.body[ds + s..ds + e]
                        .iter()
                        .map(|b| format!("{:02X}", b))
                        .collect();
                    json!(hex)
                })
                .collect();
            let oj: Vec<Value> = offsets.iter().map(|o| json!(*o)).collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "OFFSET": oj, "DATA": data})
        }
        12 => {
            // List
            let v = read_val(st, len, nc);
            let ob = nb(st);
            let os = ob.0 as usize;
            let offsets: Vec<i32> = (0..=len).map(|i| rd_i32(st.body, os + i * 4)).collect();
            let oj: Vec<Value> = offsets.iter().map(|o| json!(*o)).collect();

            let child = if !f.children.is_empty() {
                recon(st, &f.children[0])
            } else {
                json!(null)
            };
            json!({"name": f.name, "count": len, "VALIDITY": v, "OFFSET": oj, "children": [child]})
        }
        13 => {
            // Struct
            let v = read_val(st, len, nc);
            let ch: Vec<Value> = f.children.iter().map(|c| recon(st, c)).collect();
            json!({"name": f.name, "count": len, "VALIDITY": v, "children": ch})
        }
        _ => {
            // Unknown type — consume validity + data buffers
            let v = read_val(st, len, nc);
            let _ = nb(st);
            json!({"name": f.name, "count": len, "VALIDITY": v, "DATA": vec![0; len]})
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
