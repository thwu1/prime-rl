// chiptool/src/transform/common.rs — Shared transform utilities

use anyhow::bail;
use serde::{Deserialize, Serialize};
use std::collections::hash_map::Entry;
use std::collections::{BTreeMap, BTreeSet, HashMap};

use crate::ir::*;

#[derive(Debug, Clone)]
pub struct RegexSet {
    include: Vec<regex::Regex>,
    exclude: Vec<regex::Regex>,
}

impl RegexSet {
    pub fn captures<'h>(&self, haystack: &'h str) -> Option<regex::Captures<'h>> {
        for r in &self.exclude {
            if r.is_match(haystack) {
                return None;
            }
        }
        for r in &self.include {
            if let Some(c) = r.captures(haystack) {
                return Some(c);
            }
        }
        None
    }

    pub fn is_match(&self, haystack: &str) -> bool {
        for r in &self.exclude {
            if r.is_match(haystack) {
                return false;
            }
        }
        for r in &self.include {
            if r.is_match(haystack) {
                return true;
            }
        }
        false
    }
}

impl<'de> Deserialize<'de> for RegexSet {
    fn deserialize<D>(de: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        fn make_regex(r: &str) -> Result<regex::Regex, regex::Error> {
            regex::Regex::new(&format!("^{}$", r))
        }

        #[derive(Deserialize)]
        #[serde(untagged)]
        enum VecOrString {
            One(String),
            Many(Vec<String>),
        }
        impl VecOrString {
            fn regexes(self) -> Vec<regex::Regex> {
                let strs = match self {
                    VecOrString::Many(s) => s,
                    VecOrString::One(s) => vec![s],
                };
                strs.into_iter().map(|s| make_regex(&s).unwrap()).collect()
            }
        }

        impl Default for VecOrString {
            fn default() -> Self {
                Self::Many(vec![])
            }
        }

        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Inner {
            String(String),
            Complex {
                include: VecOrString,
                #[serde(default)]
                exclude: VecOrString,
            },
        }

        let x = Inner::deserialize(de)?;
        match x {
            Inner::String(s) => Ok(RegexSet {
                include: vec![make_regex(&s).unwrap()],
                exclude: vec![],
            }),
            Inner::Complex { include, exclude } => Ok(RegexSet {
                include: include.regexes(),
                exclude: exclude.regexes(),
            }),
        }
    }
}

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Clone, Copy, Serialize, Deserialize, Default)]
pub enum CheckLevel {
    NoCheck,
    Layout,
    #[default]
    Names,
    Descriptions,
}

pub(crate) fn match_all(set: impl Iterator<Item = String>, re: &RegexSet) -> BTreeSet<String> {
    let mut ids: BTreeSet<String> = BTreeSet::new();
    for id in set {
        if re.is_match(&id) {
            ids.insert(id);
        }
    }
    ids
}

pub(crate) fn match_groups(
    set: impl Iterator<Item = String>,
    re: &RegexSet,
    to: &str,
) -> BTreeMap<String, BTreeSet<String>> {
    let mut groups: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for s in set {
        if let Some(to) = match_expand(&s, re, to) {
            if let Some(v) = groups.get_mut(&to) {
                v.insert(s);
            } else {
                let mut v = BTreeSet::new();
                v.insert(s);
                groups.insert(to, v);
            }
        }
    }
    groups
}

pub(crate) fn match_expand(s: &str, regex: &RegexSet, res: &str) -> Option<String> {
    let m = regex.captures(s)?;
    let mut dst = String::new();
    m.expand(res, &mut dst);
    Some(dst)
}

pub(crate) fn replace_enum_ids(ir: &mut IR, from: &BTreeSet<String>, to: String) {
    for (_, fs) in ir.fieldsets.iter_mut() {
        for f in fs.fields.iter_mut() {
            if let Some(id) = &mut f.enumm {
                if from.contains(id) {
                    *id = to.clone()
                }
            }
        }
    }
}

pub(crate) fn replace_fieldset_ids(ir: &mut IR, from: &BTreeSet<String>, to: String) {
    for (_, b) in ir.blocks.iter_mut() {
        for i in b.items.iter_mut() {
            if let BlockItemInner::Register(r) = &mut i.inner {
                if let Some(id) = &r.fieldset {
                    if from.contains(id) {
                        r.fieldset = Some(to.clone())
                    }
                }
            }
        }
    }
}

pub(crate) fn replace_block_ids(ir: &mut IR, from: &BTreeSet<String>, to: String) {
    for (_, d) in ir.devices.iter_mut() {
        for p in d.peripherals.iter_mut() {
            if let Some(block) = &mut p.block {
                if from.contains(block) {
                    *block = to.clone()
                }
            }
        }
    }

    for (_, b) in ir.blocks.iter_mut() {
        for i in b.items.iter_mut() {
            if let BlockItemInner::Block(bi) = &mut i.inner {
                if from.contains(&bi.block) {
                    bi.block = to.clone()
                }
            }
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Copy, Clone, Eq, PartialEq, Default)]
pub enum ArrayMode {
    #[default]
    Standard,
    Cursed,
    Holey,
}

pub(crate) fn calc_array(mut offsets: Vec<u32>, mode: ArrayMode) -> anyhow::Result<(u32, Array)> {
    offsets.sort_unstable();

    let start_offset = offsets[0];
    let len = offsets.len() as u32;
    let stride = if len == 1 {
        0
    } else {
        offsets[1] - offsets[0]
    };

    if offsets
        .iter()
        .enumerate()
        .all(|(n, &i)| i == start_offset + (n as u32) * stride)
    {
        return Ok((
            start_offset,
            Array::Regular(RegularArray {
                len: offsets.len() as _,
                stride,
            }),
        ));
    }

    match mode {
        ArrayMode::Standard => {
            bail!("arrayize: items are not evenly spaced.")
        }
        ArrayMode::Cursed => {
            for o in &mut offsets {
                *o -= start_offset
            }
            Ok((start_offset, Array::Cursed(CursedArray { offsets })))
        }
        ArrayMode::Holey => {
            let len = (offsets.last().unwrap() - offsets.first().unwrap()) / stride + 1;
            Ok((start_offset, Array::Regular(RegularArray { len, stride })))
        }
    }
}
