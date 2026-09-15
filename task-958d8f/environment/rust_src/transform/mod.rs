// chiptool/src/transform/mod.rs — Transform dispatch and name-mapping utilities

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::mem::take;

use crate::ir::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum NameKind {
    Device,
    DevicePeripheral,
    DeviceInterrupt,
    Block,
    BlockItem,
    Fieldset,
    Field,
    Enum,
    EnumVariant,
}

fn rename_opt(s: &mut Option<String>, f: impl Fn(&mut String)) {
    if let Some(s) = s {
        f(s)
    }
}

pub fn map_block_names(ir: &mut IR, f: impl Fn(&mut String)) {
    remap_names(NameKind::Block, &mut ir.blocks, &f).unwrap();

    for (_, d) in ir.devices.iter_mut() {
        for p in &mut d.peripherals {
            rename_opt(&mut p.block, &f);
        }
    }

    for (_, b) in ir.blocks.iter_mut() {
        for i in b.items.iter_mut() {
            match &mut i.inner {
                BlockItemInner::Block(p) => f(&mut p.block),
                BlockItemInner::Register(_r) => {}
            }
        }
    }
}

pub fn map_fieldset_names(ir: &mut IR, f: impl Fn(&mut String)) {
    remap_names(NameKind::Fieldset, &mut ir.fieldsets, &f).unwrap();

    for (_, b) in ir.blocks.iter_mut() {
        for i in b.items.iter_mut() {
            match &mut i.inner {
                BlockItemInner::Block(_p) => {}
                BlockItemInner::Register(r) => rename_opt(&mut r.fieldset, &f),
            }
        }
    }
}

pub fn map_enum_names(ir: &mut IR, f: impl Fn(&mut String)) {
    remap_names(NameKind::Enum, &mut ir.enums, &f).unwrap();

    for (_, fs) in ir.fieldsets.iter_mut() {
        for ff in fs.fields.iter_mut() {
            rename_opt(&mut ff.enumm, &f);
        }
    }
}

pub fn map_device_names(ir: &mut IR, f: impl Fn(&mut String)) {
    remap_names(NameKind::Device, &mut ir.devices, &f).unwrap();
}

pub fn map_block_item_names(ir: &mut IR, f: impl Fn(&mut String)) {
    for (_, b) in ir.blocks.iter_mut() {
        for i in b.items.iter_mut() {
            f(&mut i.name)
        }
    }
}

pub fn map_field_names(ir: &mut IR, f: impl Fn(&mut String)) {
    for (_, fs) in ir.fieldsets.iter_mut() {
        for ff in fs.fields.iter_mut() {
            f(&mut ff.name)
        }
    }
}

pub fn map_enum_variant_names(ir: &mut IR, f: impl Fn(&mut String)) {
    for (_, e) in ir.enums.iter_mut() {
        for v in e.variants.iter_mut() {
            f(&mut v.name)
        }
    }
}

fn remap_names<T>(
    _kind: NameKind,
    x: &mut BTreeMap<String, T>,
    f: impl Fn(&mut String),
) -> Result<(), ()> {
    let mut res = BTreeMap::new();

    for (mut name, val) in take(x) {
        f(&mut name);
        res.insert(name, val);
    }

    *x = res;
    Ok(())
}

pub mod common;

macro_rules! transforms {
    ($($mod:ident::$struct:ident,)*) => {
        $( pub mod $mod; )*

        #[derive(Debug, Serialize, Deserialize)]
        pub enum Transform {
            $( $struct($mod::$struct), )*
        }

        impl Transform {
            pub fn run(&self, ir: &mut IR) -> anyhow::Result<()> {
                match self {
                    $( Self::$struct(t) => t.run(ir), )*
                }
            }
        }
    };
}

transforms!(
    sanitize::Sanitize,
    sort::Sort,
    add::Add,
    delete::Delete,
    delete_enums::DeleteEnums,
    delete_fields::DeleteFields,
    delete_fieldsets::DeleteFieldsets,
    delete_registers::DeleteRegisters,
    merge_blocks::MergeBlocks,
    merge_enums::MergeEnums,
    merge_fieldsets::MergeFieldsets,
    rename::Rename,
    rename_fields::RenameFields,
    rename_registers::RenameRegisters,
    make_register_array::MakeRegisterArray,
    make_field_array::MakeFieldArray,
    make_block::MakeBlock,
    modify_byte_offset::ModifyByteOffset,
    modify_registers::ModifyRegisters,
);
