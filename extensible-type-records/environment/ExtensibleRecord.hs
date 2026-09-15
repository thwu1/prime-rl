{-# LANGUAGE AllowAmbiguousTypes  #-}
{-# LANGUAGE ConstraintKinds      #-}
{-# LANGUAGE DataKinds            #-}
{-# LANGUAGE FlexibleContexts     #-}
{-# LANGUAGE FlexibleInstances    #-}
{-# LANGUAGE GADTs                #-}
{-# LANGUAGE MultiParamTypeClasses #-}
{-# LANGUAGE OverloadedLabels     #-}
{-# LANGUAGE PolyKinds            #-}
{-# LANGUAGE ScopedTypeVariables  #-}
{-# LANGUAGE TypeApplications     #-}
{-# LANGUAGE TypeFamilies         #-}
{-# LANGUAGE TypeOperators        #-}
{-# LANGUAGE UndecidableInstances #-}


module ExtensibleRecord where

import Data.Kind (Type, Constraint)
import Data.Proxy (Proxy (..))
import FCF
import GHC.OverloadedLabels (IsLabel (..))
import GHC.TypeLits
import Unsafe.Coerce (unsafeCoerce)

------------------------------------------------------------------------
-- Core types
------------------------------------------------------------------------

-- | Existential wrapper: hides the type index of @f@.
data Any (f :: k -> Type) where
  Any :: f t -> Any f

-- | Type-safe extensible record indexed by a type-level association list.
-- The internal @[Any f]@ maintains positional correspondence with @ts@.
data OpenProduct (f :: k -> Type) (ts :: [(Symbol, k)]) where
  OpenProduct :: [Any f] -> OpenProduct f ts

-- | A proxy for type-level field names.
data Key (key :: Symbol) = Key

instance (key ~ key') => IsLabel key (Key key') where
  fromLabel = Key

-- | The empty product.
nil :: OpenProduct f '[]
nil = OpenProduct []

------------------------------------------------------------------------
-- Uniqueness checking — BROKEN: allows duplicate keys
------------------------------------------------------------------------

-- | Should return 'True iff @key@ does not appear in @ts@.
-- BROKEN: currently always returns 'True.
type UniqueKey (key :: k) (ts :: [(k, t)]) = Pure 'True

-- | Should emit a custom TypeError when a duplicate key is inserted.
-- BROKEN: currently always produces the trivial constraint.
type family RequireUniqueKey
    (result :: Bool) (key :: Symbol) (t :: k) (ts :: [(Symbol, k)])
    :: Constraint where
  RequireUniqueKey _result _key _t _ts = ()

-- | Insert a new field. Uses RequireUniqueKey constraint (fix the
-- type families above to enforce uniqueness).
insert
    :: RequireUniqueKey (Eval (UniqueKey key ts)) key t ts
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f ('(key, t) ': ts)
insert _ ft (OpenProduct v) = OpenProduct $ Any ft : v

------------------------------------------------------------------------
-- Field lookup — type families provided, term functions are stubs
------------------------------------------------------------------------

-- | Compute the 0-based index of @key@ in @ts@.
-- Gets stuck (produces a type error) if @key@ is absent.
type FindElem (key :: Symbol) (ts :: [(Symbol, k)]) =
  Eval (FromMaybe Stuck =<< FindIndex (TyEq key <=< Fst) ts)

-- | Reify 'FindElem' to a term-level 'Int'.
findElem :: forall key ts. KnownNat (FindElem key ts) => Int
findElem = undefined  -- TODO: implement

-- | Look up the type associated with @key@ in @ts@.
type LookupType (key :: k) (ts :: [(k, t)]) =
  FromMaybe Stuck =<< Lookup key ts

-- | Retrieve the value stored at @key@.
get
    :: forall key ts f
     . KnownNat (FindElem key ts)
    => Key key
    -> OpenProduct f ts
    -> f (Eval (LookupType key ts))
get = undefined  -- TODO: implement

------------------------------------------------------------------------
-- Update
------------------------------------------------------------------------

-- | Compute the type list after replacing the value at @key@.
type UpdateElem (key :: Symbol) (t :: k) (ts :: [(Symbol, k)]) =
  SetIndex (FindElem key ts) '(key, t) ts

-- | Replace the value at @key@ (may change its type).
update
    :: forall key ts t f
     . KnownNat (FindElem key ts)
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f (Eval (UpdateElem key t ts))
update = undefined  -- TODO: implement

------------------------------------------------------------------------
-- Delete
------------------------------------------------------------------------

-- | Compute the type list after removing @key@.
type DeleteElem key = Filter (Not <=< TyEq key <=< Fst)

-- | Remove the field at @key@.
delete
    :: forall key ts f
     . KnownNat (FindElem key ts)
    => Key key
    -> OpenProduct f ts
    -> OpenProduct f (Eval (DeleteElem key ts))
delete = undefined  -- TODO: implement

------------------------------------------------------------------------
-- Upsert (insert-or-update) — INCOMPLETE
------------------------------------------------------------------------

-- | Find the index of @key@ in @ts@, or 'Nothing if absent.
-- BROKEN: always returns 'Nothing.
type UpsertLoc (key :: Symbol) (ts :: [(Symbol, k)]) = 'Nothing

-- | Compute the result type list after an upsert.
-- Should prepend if the key is absent, or replace in-place if present.
-- BROKEN: always prepends.
type UpsertElem (key :: Symbol) (t :: k) (ts :: [(Symbol, k)]) =
  Pure ('(key, t) ': ts)

-- | Reify a type-level @Maybe Nat@ to a term-level @Maybe Int@.
class FindUpsertElem (a :: Maybe Nat) where
  upsertElem :: Maybe Int

instance FindUpsertElem 'Nothing where
  upsertElem = Nothing

-- TODO: add instance for ('Just n)

-- | Insert if @key@ is absent, update if present.
upsert
    :: forall key ts t f
     . FindUpsertElem (UpsertLoc key ts)
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f (Eval (UpsertElem key t ts))
upsert = undefined  -- TODO: implement

------------------------------------------------------------------------
-- Destructuring
------------------------------------------------------------------------

-- | Split the first field from a non-empty product.
peel
    :: forall f name t ts
     . OpenProduct f ('(name, t) ': ts)
    -> (f t, OpenProduct f ts)
peel = undefined  -- TODO: implement

------------------------------------------------------------------------
-- Equality — MISSING
------------------------------------------------------------------------

-- TODO: Eq instance for OpenProduct f '[]
-- TODO: Eq instance for OpenProduct f ('(name, t) ': ts)

------------------------------------------------------------------------
-- Merge — INCOMPLETE
------------------------------------------------------------------------

-- | Assert that every key in @ts1@ is absent from @ts2@.
-- BROKEN: always produces the trivial constraint.
type family AllKeysUnique
    (ts1 :: [(Symbol, k)]) (ts2 :: [(Symbol, k)]) :: Constraint where
  AllKeysUnique _ts1 _ts2 = ()

-- | Combine two products with disjoint key sets.
merge
    :: AllKeysUnique ts1 ts2
    => OpenProduct f ts1
    -> OpenProduct f ts2
    -> OpenProduct f (Eval (Append ts1 ts2))
merge = undefined  -- TODO: implement
