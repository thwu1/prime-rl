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

data Any (f :: k -> Type) where
  Any :: f t -> Any f

data OpenProduct (f :: k -> Type) (ts :: [(Symbol, k)]) where
  OpenProduct :: [Any f] -> OpenProduct f ts

data Key (key :: Symbol) = Key

instance (key ~ key') => IsLabel key (Key key') where
  fromLabel = Key

nil :: OpenProduct f '[]
nil = OpenProduct []

------------------------------------------------------------------------
-- Uniqueness checking
------------------------------------------------------------------------

type UniqueKey (key :: k) (ts :: [(k, t)]) =
  Null =<< Filter (TyEq key <=< Fst) ts

type family RequireUniqueKey
    (result :: Bool) (key :: Symbol) (t :: k) (ts :: [(Symbol, k)])
    :: Constraint where
  RequireUniqueKey 'True  _key _t _ts = ()
  RequireUniqueKey 'False key   t  ts =
    TypeError
         ( 'Text "Attempting to add a field named `"
     ':<>: 'Text key
     ':<>: 'Text "' with type "
     ':<>: 'ShowType t
     ':<>: 'Text " to an OpenProduct."
     ':$$: 'Text "But the OpenProduct already has a field `"
     ':<>: 'Text key
     ':<>: 'Text "' with type "
     ':<>: 'ShowType (Eval (LookupType key ts))
     ':$$: 'Text "Consider using `upsert' instead of `insert'."
         )

insert
    :: RequireUniqueKey (Eval (UniqueKey key ts)) key t ts
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f ('(key, t) ': ts)
insert _ ft (OpenProduct v) = OpenProduct $ Any ft : v

------------------------------------------------------------------------
-- Field lookup
------------------------------------------------------------------------

type FindElem (key :: Symbol) (ts :: [(Symbol, k)]) =
  Eval (FromMaybe Stuck =<< FindIndex (TyEq key <=< Fst) ts)

findElem :: forall key ts. KnownNat (FindElem key ts) => Int
findElem = fromIntegral . natVal $ Proxy @(FindElem key ts)

type LookupType (key :: k) (ts :: [(k, t)]) =
  FromMaybe Stuck =<< Lookup key ts

get
    :: forall key ts f
     . KnownNat (FindElem key ts)
    => Key key
    -> OpenProduct f ts
    -> f (Eval (LookupType key ts))
get _ (OpenProduct v) =
    unAny $ v !! findElem @key @ts
  where
    unAny (Any a) = unsafeCoerce a

------------------------------------------------------------------------
-- Update
------------------------------------------------------------------------

type UpdateElem (key :: Symbol) (t :: k) (ts :: [(Symbol, k)]) =
  SetIndex (FindElem key ts) '(key, t) ts

update
    :: forall key ts t f
     . KnownNat (FindElem key ts)
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f (Eval (UpdateElem key t ts))
update _ ft (OpenProduct v) =
    let i = findElem @key @ts
    in OpenProduct $ take i v ++ [Any ft] ++ drop (i + 1) v

------------------------------------------------------------------------
-- Delete
------------------------------------------------------------------------

type DeleteElem key = Filter (Not <=< TyEq key <=< Fst)

delete
    :: forall key ts f
     . KnownNat (FindElem key ts)
    => Key key
    -> OpenProduct f ts
    -> OpenProduct f (Eval (DeleteElem key ts))
delete _ (OpenProduct v) =
    let i = findElem @key @ts
        (a, b) = splitAt i v
    in OpenProduct $ a ++ tail b

------------------------------------------------------------------------
-- Upsert (insert-or-update)
------------------------------------------------------------------------

-- Workaround for the inability to partially apply type families.
-- Placeholder1Of3 f b c a  ~>  f a b c
data Placeholder1Of3 :: (a -> b -> c -> Exp r) -> b -> c -> a -> Exp r
type instance Eval (Placeholder1Of3 f b c a) = Eval (f a b c)

type UpsertLoc (key :: Symbol) (ts :: [(Symbol, k)]) =
  Eval (FindIndex (TyEq key <=< Fst) ts)

type UpsertElem (key :: Symbol) (t :: k) (ts :: [(Symbol, k)]) =
  FromMaybe ('(key, t) ': ts)
    =<< Map (Placeholder1Of3 SetIndex '(key, t) ts)
    =<< FindIndex (TyEq key <=< Fst) ts

class FindUpsertElem (a :: Maybe Nat) where
  upsertElem :: Maybe Int

instance FindUpsertElem 'Nothing where
  upsertElem = Nothing

instance KnownNat n => FindUpsertElem ('Just n) where
  upsertElem = Just . fromIntegral . natVal $ Proxy @n

upsert
    :: forall key ts t f
     . FindUpsertElem (UpsertLoc key ts)
    => Key key
    -> f t
    -> OpenProduct f ts
    -> OpenProduct f (Eval (UpsertElem key t ts))
upsert _ ft (OpenProduct v) =
  OpenProduct $ case upsertElem @(UpsertLoc key ts) of
    Nothing -> Any ft : v
    Just n  -> take n v ++ [Any ft] ++ drop (n + 1) v

------------------------------------------------------------------------
-- Destructuring
------------------------------------------------------------------------

peel
    :: forall f name t ts
     . OpenProduct f ('(name, t) ': ts)
    -> (f t, OpenProduct f ts)
peel z@(OpenProduct v) =
  ( get (Key @name) z
  , OpenProduct $ tail v
  )

------------------------------------------------------------------------
-- Equality
------------------------------------------------------------------------

instance Eq (OpenProduct f '[]) where
  _ == _ = True

instance (Eq (f t), Eq (OpenProduct f ts))
      => Eq (OpenProduct f ('(name, t) ': ts)) where
  a == b = peel a == peel b

------------------------------------------------------------------------
-- Merge
------------------------------------------------------------------------

type family AllKeysUnique
    (ts1 :: [(Symbol, k)]) (ts2 :: [(Symbol, k)]) :: Constraint where
  AllKeysUnique '[] _ts2 = ()
  AllKeysUnique ('(key, _t) ': rest) ts2 =
    (Eval (UniqueKey key ts2) ~ 'True, AllKeysUnique rest ts2)

merge
    :: AllKeysUnique ts1 ts2
    => OpenProduct f ts1
    -> OpenProduct f ts2
    -> OpenProduct f (Eval (Append ts1 ts2))
merge (OpenProduct v1) (OpenProduct v2) = OpenProduct (v1 ++ v2)
