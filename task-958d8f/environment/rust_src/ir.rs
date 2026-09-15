// chiptool/src/ir.rs — Intermediate Representation data model
//
// The IR stores hardware peripheral register descriptions as four namespaces:
//   devices, blocks, fieldsets, enums
// Cross-references link them: register items reference fieldsets,
// fieldset fields reference enums, block items reference other blocks.

use std::collections::BTreeMap;
use std::ops::RangeInclusive;

#[derive(Default, Clone, Debug, PartialEq)]
pub struct IR {
    pub devices: BTreeMap<String, Device>,
    pub blocks: BTreeMap<String, Block>,
    pub fieldsets: BTreeMap<String, FieldSet>,
    pub enums: BTreeMap<String, Enum>,
}

impl IR {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn merge(&mut self, other: IR) {
        self.devices.extend(other.devices);
        self.blocks.extend(other.blocks);
        self.fieldsets.extend(other.fieldsets);
        self.enums.extend(other.enums);
    }
}

macro_rules! get_mut {
    ($ir:expr, $type:ident, $name:expr) => {
        $ir.$type.get_mut($name).ok_or_else(|| {
            anyhow::anyhow!("Failed to find element {} in {}", $name, stringify!($type))
        })
    };
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Device {
    pub nvic_priority_bits: Option<u8>,
    pub peripherals: Vec<Peripheral>,
    pub interrupts: Vec<Interrupt>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Peripheral {
    pub name: String,
    pub description: Option<String>,
    pub base_address: u64,
    pub array: Option<Array>,
    pub block: Option<String>,
    pub interrupts: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Interrupt {
    pub name: String,
    pub description: Option<String>,
    pub value: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Block {
    pub extends: Option<String>,
    pub description: Option<String>,
    pub items: Vec<BlockItem>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BlockItem {
    pub name: String,
    pub description: Option<String>,
    pub array: Option<Array>,
    pub byte_offset: u32,
    #[serde(flatten)]
    pub inner: BlockItemInner,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum BlockItemInner {
    Block(BlockItemBlock),
    Register(Register),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Array {
    Regular(RegularArray),
    Cursed(CursedArray),
}

impl Array {
    pub fn len(&self) -> usize {
        match self {
            Self::Regular(x) => x.len as usize,
            Self::Cursed(x) => x.offsets.len(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RegularArray {
    pub len: u32,
    pub stride: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CursedArray {
    pub offsets: Vec<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Register {
    #[serde(default = "default_readwrite")]
    pub access: Access,
    #[serde(default = "default_32")]
    pub bit_size: u32,
    pub fieldset: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BlockItemBlock {
    pub block: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Access {
    ReadWrite,
    Read,
    Write,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FieldSet {
    pub extends: Option<String>,
    pub description: Option<String>,
    #[serde(default = "default_32")]
    pub bit_size: u32,
    pub fields: Vec<Field>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Eq)]
#[serde(untagged)]
pub enum BitOffset {
    Regular(u32),
    Cursed(Vec<RangeInclusive<u32>>),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Field {
    pub name: String,
    pub description: Option<String>,
    pub bit_offset: BitOffset,
    pub bit_size: u32,
    pub array: Option<Array>,
    #[serde(rename = "enum")]
    pub enumm: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Enum {
    pub description: Option<String>,
    pub bit_size: u32,
    pub variants: Vec<EnumVariant>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EnumVariant {
    pub name: String,
    pub description: Option<String>,
    pub value: u64,
}

fn default_32() -> u32 { 32 }
fn default_readwrite() -> Access { Access::ReadWrite }
