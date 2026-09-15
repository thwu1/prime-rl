{-# LANGUAGE DataKinds            #-}
{-# LANGUAGE PolyKinds            #-}
{-# LANGUAGE TypeFamilies         #-}
{-# LANGUAGE TypeOperators        #-}
{-# LANGUAGE UndecidableInstances #-}


module FCF where

import Data.Kind (Type)
import GHC.TypeLits (Nat, type (+), type (-))

-- | A type-level expression producing a value of kind @a@ when evaluated.
type Exp a = a -> Type

-- | Evaluate a type-level expression.
type family Eval (e :: Exp a) :: a

-- | Lift a value into Exp (type-level pure/return).
data Pure :: a -> Exp a
type instance Eval (Pure x) = x

-- | Monadic bind: evaluate the expression, then apply the function.
data (=<<) :: (a -> Exp b) -> Exp a -> Exp b
type instance Eval (k =<< e) = Eval (k (Eval e))
infixr 0 =<<

-- | Kleisli composition of type-level functions.
data (<=<) :: (b -> Exp c) -> (a -> Exp b) -> a -> Exp c
type instance Eval ((f <=< g) x) = Eval (f (Eval (g x)))
infixr 1 <=<

-- | Project the first element of a type-level pair.
data Fst :: (a, b) -> Exp a
type instance Eval (Fst '(a, _b)) = a

-- | Project the second element of a type-level pair.
data Snd :: (a, b) -> Exp b
type instance Eval (Snd '(_a, b)) = b

-- | Type-level boolean negation.
data Not :: Bool -> Exp Bool
type instance Eval (Not 'True) = 'False
type instance Eval (Not 'False) = 'True

-- | Type-level equality test.
data TyEq :: a -> b -> Exp Bool
type instance Eval (TyEq a b) = TyEqImpl a b

type family TyEqImpl (a :: k) (b :: k) :: Bool where
  TyEqImpl a a = 'True
  TyEqImpl a b = 'False

-- | Extract from Maybe with a default.
data FromMaybe :: a -> Maybe a -> Exp a
type instance Eval (FromMaybe _def ('Just a)) = a
type instance Eval (FromMaybe def 'Nothing)   = def

-- | Polymorphic map over type-level functors (lists and Maybe).
data Map :: (a -> Exp b) -> f a -> Exp (f b)

-- List instances
type instance Eval (Map _f '[])       = '[]
type instance Eval (Map f (a ': as))  = Eval (f a) ': Eval (Map f as)

-- Maybe instances
type instance Eval (Map _f 'Nothing)  = 'Nothing
type instance Eval (Map f ('Just a))  = 'Just (Eval (f a))

-- | Filter a type-level list by a predicate.
data Filter :: (a -> Exp Bool) -> [a] -> Exp [a]
type instance Eval (Filter _p '[])      = '[]
type instance Eval (Filter p (a ': as)) = FilterAux (Eval (p a)) a (Filter p as)

type family FilterAux (keep :: Bool) (x :: k) (rest :: Exp [k]) :: [k] where
  FilterAux 'True  a rest = a ': Eval rest
  FilterAux 'False _a rest = Eval rest

-- | Check if a type-level list is empty.
data Null :: [a] -> Exp Bool
type instance Eval (Null '[])        = 'True
type instance Eval (Null (_a ': _as)) = 'False

-- | Find the index of the first element satisfying a predicate.
data FindIndex :: (a -> Exp Bool) -> [a] -> Exp (Maybe Nat)
type instance Eval (FindIndex _p '[])      = 'Nothing
type instance Eval (FindIndex p (a ': as)) =
  FindIndexAux (Eval (p a)) (FindIndex p as)

type family FindIndexAux (found :: Bool) (rest :: Exp (Maybe Nat)) :: Maybe Nat where
  FindIndexAux 'True  _rest = 'Just 0
  FindIndexAux 'False rest  = MapIncr (Eval rest)

type family MapIncr (m :: Maybe Nat) :: Maybe Nat where
  MapIncr 'Nothing  = 'Nothing
  MapIncr ('Just n) = 'Just (n + 1)

-- | Look up a key in a type-level association list.
data Lookup :: k -> [(k, v)] -> Exp (Maybe v)
type instance Eval (Lookup _key '[]) = 'Nothing
type instance Eval (Lookup key ('(k, v) ': rest)) =
  LookupAux (TyEqImpl key k) v (Lookup key rest)

type family LookupAux (eq :: Bool) (v :: t) (rest :: Exp (Maybe t)) :: Maybe t where
  LookupAux 'True  v _rest = 'Just v
  LookupAux 'False _v rest = Eval rest

-- | Replace the element at index @n@ in a type-level list.
data SetIndex :: Nat -> a -> [a] -> Exp [a]
type instance Eval (SetIndex n a xs) = SetIndexImpl n a xs

type family SetIndexImpl (n :: Nat) (x :: k) (xs :: [k]) :: [k] where
  SetIndexImpl 0 a (_x ': rest) = a ': rest
  SetIndexImpl n a (x ': rest)  = x ': SetIndexImpl (n - 1) a rest

-- | Append two type-level lists.
data Append :: [a] -> [a] -> Exp [a]
type instance Eval (Append '[] ys)       = ys
type instance Eval (Append (x ': xs) ys) = x ': Eval (Append xs ys)

-- | A type family that never reduces. Used to signal missing keys.
type family Stuck :: a
