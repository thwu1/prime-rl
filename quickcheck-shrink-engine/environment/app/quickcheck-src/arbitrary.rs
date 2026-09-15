// Excerpts from BurntSushi's quickcheck crate — arbitrary.rs
// https://github.com/BurntSushi/quickcheck
// License: MIT / UNLICENSE
//
// This file contains the Arbitrary trait, shrinking implementations,
// and the VecShrinker used for shrinking vectors.

use std::iter::{empty, once};

/// Creates a shrinker with zero elements.
pub fn empty_shrinker<A: 'static>() -> Box<dyn Iterator<Item = A>> {
    Box::new(empty())
}

/// Creates a shrinker with a single element.
pub fn single_shrinker<A: 'static>(value: A) -> Box<dyn Iterator<Item = A>> {
    Box::new(once(value))
}

/// `Arbitrary` describes types whose values can be randomly generated and
/// shrunk.
pub trait Arbitrary: Clone + 'static {
    fn arbitrary(g: &mut Gen) -> Self;

    /// Return an iterator of values that are smaller than itself.
    fn shrink(&self) -> Box<dyn Iterator<Item = Self>> {
        empty_shrinker()
    }
}

impl Arbitrary for bool {
    fn arbitrary(g: &mut Gen) -> bool {
        g.random()
    }

    fn shrink(&self) -> Box<dyn Iterator<Item = bool>> {
        if *self {
            single_shrinker(false)
        } else {
            empty_shrinker()
        }
    }
}

// ---------------------------------------------------------------------------
// Unsigned integer shrinking
// ---------------------------------------------------------------------------

macro_rules! unsigned_shrinker {
    ($ty:ty) => {
        mod shrinker {
            pub struct UnsignedShrinker {
                x: $ty,
                i: $ty,
            }

            impl UnsignedShrinker {
                pub fn new(x: $ty) -> Box<dyn Iterator<Item = $ty>> {
                    if x == 0 {
                        super::empty_shrinker()
                    } else {
                        Box::new(
                            vec![0]
                                .into_iter()
                                .chain(UnsignedShrinker { x, i: x / 2 }),
                        )
                    }
                }
            }

            impl Iterator for UnsignedShrinker {
                type Item = $ty;
                fn next(&mut self) -> Option<$ty> {
                    if self.x - self.i < self.x {
                        let result = Some(self.x - self.i);
                        self.i /= 2;
                        result
                    } else {
                        None
                    }
                }
            }
        }
    };
}

// ---------------------------------------------------------------------------
// Signed integer shrinking
// ---------------------------------------------------------------------------

macro_rules! signed_shrinker {
    ($ty:ty) => {
        mod shrinker {
            pub struct SignedShrinker {
                x: $ty,
                i: $ty,
            }

            impl SignedShrinker {
                pub fn new(x: $ty) -> Box<dyn Iterator<Item = $ty>> {
                    if x == 0 {
                        super::empty_shrinker()
                    } else {
                        let shrinker = SignedShrinker { x, i: x / 2 };
                        let mut items = vec![0];
                        if shrinker.i < 0 && shrinker.x != <$ty>::MIN {
                            items.push(shrinker.x.abs());
                        }
                        Box::new(items.into_iter().chain(shrinker))
                    }
                }
            }

            impl Iterator for SignedShrinker {
                type Item = $ty;
                fn next(&mut self) -> Option<$ty> {
                    if self.i != 0 {
                        let result = Some(self.x - self.i);
                        self.i /= 2;
                        result
                    } else {
                        None
                    }
                }
            }
        }
    };
}

// ---------------------------------------------------------------------------
// Vec shrinking (VecShrinker)
// ---------------------------------------------------------------------------

impl<A: Arbitrary> Arbitrary for Vec<A> {
    fn arbitrary(g: &mut Gen) -> Vec<A> {
        let size = {
            let s = g.size();
            g.random_range(0..s)
        };
        (0..size).map(|_| A::arbitrary(g)).collect()
    }

    fn shrink(&self) -> Box<dyn Iterator<Item = Vec<A>>> {
        VecShrinker::new(self.clone())
    }
}

/// Iterator which returns successive attempts to shrink the vector `seed`
struct VecShrinker<A> {
    seed: Vec<A>,
    /// How much which is removed when trying with smaller vectors
    size: usize,
    /// The end of the removed elements
    offset: usize,
    /// The shrinker for the element at `offset` once shrinking of individual
    /// elements are attempted
    element_shrinker: Box<dyn Iterator<Item = A>>,
}

impl<A: Arbitrary> VecShrinker<A> {
    fn new(seed: Vec<A>) -> Box<dyn Iterator<Item = Vec<A>>> {
        let es = match seed.first() {
            Some(e) => e.shrink(),
            None => return empty_shrinker(),
        };
        let size = seed.len();
        Box::new(VecShrinker {
            seed,
            size,
            offset: size,
            element_shrinker: es,
        })
    }

    /// Returns the next shrunk element if any, `offset` points to the index
    /// after the returned element after the function returns
    fn next_element(&mut self) -> Option<A> {
        loop {
            match self.element_shrinker.next() {
                Some(e) => return Some(e),
                None => match self.seed.get(self.offset) {
                    Some(e) => {
                        self.element_shrinker = e.shrink();
                        self.offset += 1;
                    }
                    None => return None,
                },
            }
        }
    }
}

impl<A> Iterator for VecShrinker<A>
where
    A: Arbitrary,
{
    type Item = Vec<A>;
    fn next(&mut self) -> Option<Vec<A>> {
        // Try with an empty vector first
        if self.size == self.seed.len() {
            self.size /= 2;
            self.offset = self.size;
            return Some(vec![]);
        }
        if self.size != 0 {
            // Generate a smaller vector by removing the elements between
            // (offset - size) and offset
            let xs1 = self.seed[..(self.offset - self.size)]
                .iter()
                .chain(&self.seed[self.offset..])
                .cloned()
                .collect();
            self.offset += self.size;
            // Try to reduce the amount removed from the vector once all
            // previous sizes tried
            if self.offset > self.seed.len() {
                self.size /= 2;
                self.offset = self.size;
            }
            Some(xs1)
        } else {
            // A smaller vector did not work so try to shrink each element of
            // the vector instead. Reuse `offset` as the index determining which
            // element to shrink

            // The first element shrinker is already created so skip the first
            // offset (self.offset == 0 only on first entry to this part of the
            // iterator)
            if self.offset == 0 {
                self.offset = 1;
            }

            match self.next_element() {
                Some(e) => Some(
                    self.seed[..self.offset - 1]
                        .iter()
                        .cloned()
                        .chain(Some(e))
                        .chain(self.seed[self.offset..].iter().cloned())
                        .collect(),
                ),
                None => None,
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tuple shrinking
// ---------------------------------------------------------------------------

macro_rules! impl_arb_for_single_tuple {
    ($(($type_param:ident, $tuple_index:tt),)*) => {
        impl<$($type_param),*> Arbitrary for ($($type_param,)*)
            where $($type_param: Arbitrary,)*
        {
            fn arbitrary(g: &mut Gen) -> ($($type_param,)*) {
                (
                    $(
                        $type_param::arbitrary(g),
                    )*
                )
            }

            fn shrink(&self) -> Box<dyn Iterator<Item=($($type_param,)*)>> {
                let iter = ::std::iter::empty();
                $(
                    let cloned = self.clone();
                    let iter = iter.chain(
                        self.$tuple_index.shrink().map(move |shr_value| {
                            let mut result = cloned.clone();
                            result.$tuple_index = shr_value;
                            result
                        })
                    );
                )*
                Box::new(iter)
            }
        }
    };
}
