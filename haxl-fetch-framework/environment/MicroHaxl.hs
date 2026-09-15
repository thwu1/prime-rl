{-# LANGUAGE GADTs #-}
{-# LANGUAGE ExistentialQuantification #-}
{-# LANGUAGE RankNTypes #-}
{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE TypeFamilies #-}
{-# LANGUAGE MultiParamTypeClasses #-}
{-# LANGUAGE FlexibleInstances #-}
{-# LANGUAGE FlexibleContexts #-}
{-# LANGUAGE DeriveDataTypeable #-}
{-# LANGUAGE StandaloneDeriving #-}
{-# LANGUAGE BangPatterns #-}
{-# LANGUAGE RecordWildCards #-}


-- | MicroHaxl: A minimal concurrent data-fetching framework inspired by Haxl.
-- This module implements GADT-based request types, automatic batching via
-- Applicative, request deduplication, and fetch-round statistics.

module MicroHaxl
  ( -- * Core types
    Fetch(..)
  , Result(..)
  , BlockedFetch(..)
  , ResultVar
  , mkResultVar
  , putResult
  , putFailure
  , putSuccess

    -- * DataSource class
  , DataSource(..)
  , DataSourceState(..)

    -- * State store
  , StateStore
  , emptyStateStore
  , stateSet
  , stateGet

    -- * Environment
  , Env(..)
  , initEnv

    -- * Running
  , runFetch

    -- * Stats
  , Stats(..)
  , emptyStats

    -- * Cache
  , CacheKey(..)

    -- * User-facing request functions
  , dataFetch
  , preFetch

    -- * Applicative combinators
  , pairFetch
  , traverseFetch
  ) where

import Control.Concurrent
import Control.Exception (SomeException, Exception, try, throwIO, toException, catch)
import Data.IORef
import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Typeable
import Data.Hashable
import Data.Proxy
import Unsafe.Coerce (unsafeCoerce)


-- ---------------------------------------------------------------------------
-- Result variables

-- | A sink for the result of a data fetch.
newtype ResultVar a = ResultVar (MVar (Either SomeException a))

mkResultVar :: IO (ResultVar a)
mkResultVar = ResultVar <$> newEmptyMVar

putResult :: ResultVar a -> Either SomeException a -> IO ()
putResult (ResultVar mv) = putMVar mv

putFailure :: Exception e => ResultVar a -> e -> IO ()
putFailure rv e = putResult rv (Left (toException e))

putSuccess :: ResultVar a -> a -> IO ()
putSuccess rv a = putResult rv (Right a)

readResultVar :: ResultVar a -> IO (Either SomeException a)
readResultVar (ResultVar mv) = readMVar mv

-- ---------------------------------------------------------------------------
-- Blocked fetches

-- | A blocked fetch: a request paired with where to put the result.
data BlockedFetch r = forall a. (Typeable a, Show a) =>
  BlockedFetch (r a) (ResultVar a)

-- ---------------------------------------------------------------------------
-- DataSource class

-- | Typeclass for data sources. Each data source must implement 'fetch',
-- which takes a list of blocked fetches and performs them.
class (Typeable r) => DataSource r where
  dataSourceName :: r a -> String
  fetch :: SourceState r -> [BlockedFetch r] -> IO ()

-- | State associated with a data source.
class Typeable r => DataSourceState r where
  data SourceState r

-- ---------------------------------------------------------------------------
-- State Store

-- | Existential wrapper for data source states.
data SomeState = forall r. (DataSource r, DataSourceState r) =>
  SomeState (SourceState r)

-- | A heterogeneous store mapping data source types to their states.
newtype StateStore = StateStore (Map TypeRep SomeState)

emptyStateStore :: StateStore
emptyStateStore = StateStore Map.empty

stateSet :: forall r. (DataSource r, DataSourceState r)
         => Proxy r -> SourceState r -> StateStore -> StateStore
stateSet p st (StateStore m) =
  StateStore (Map.insert (typeRep p) (SomeState st) m)

stateGet :: forall r. (Typeable r) => Proxy r -> StateStore -> Maybe (SourceState r)
stateGet p (StateStore m) = case Map.lookup (typeRep p) m of
  Nothing -> Nothing
  Just (SomeState st) -> Just (unsafeCoerce st)

-- ---------------------------------------------------------------------------
-- Cache

-- | A key for the request cache.
data CacheKey = forall r a. (DataSource r, Typeable a, Typeable r,
  Eq (r a), Hashable (r a), Show (r a)) =>
  CacheKey TypeRep (r a)

-- | A cached result, existentially quantified.
data CachedResult = forall a. Typeable a => CachedResult (ResultVar a)

-- | Build a string cache key from a request.
makeCacheKeyStr :: (Show (r a)) => r a -> String
makeCacheKeyStr req = show req

-- ---------------------------------------------------------------------------
-- Stats

data Stats = Stats
  { statsFetchRounds :: !Int        -- ^ Number of fetch rounds executed
  , statsFetchTotal  :: !Int        -- ^ Total individual fetches
  , statsBatchSizes  :: [Int]       -- ^ Size of each batch (per round)
  , statsDatasources :: Map String Int  -- ^ Fetches per data source
  } deriving (Show, Eq)

emptyStats :: Stats
emptyStats = Stats 0 0 [] Map.empty

-- ---------------------------------------------------------------------------
-- The Fetch monad

-- | The result of running a Fetch computation one step.
data Result a
  = Done a
  | forall b. Blocked [SomeBlockedFetch] (Fetch a)

-- | Existential wrapper for blocked fetches from potentially different
-- data sources.
data SomeBlockedFetch = forall r. (DataSource r, DataSourceState r) =>
  SomeBlockedFetch (BlockedFetch r) TypeRep

-- | The Fetch monad. A computation that may block on data fetches.
newtype Fetch a = Fetch { unFetch :: Env -> IO (Result a) }

instance Functor Fetch where
  fmap f (Fetch m) = Fetch $ \env -> do
    r <- m env
    case r of
      Done a -> return (Done (f a))
      Blocked reqs cont -> return (Blocked reqs (fmap f cont))

instance Applicative Fetch where
  pure a = Fetch $ \_ -> return (Done a)

  Fetch ff <*> Fetch fa = Fetch $ \env -> do
    rf <- ff env
    case rf of
      Done f -> do
        ra <- fa env
        case ra of
          Done a -> return (Done (f a))
          Blocked reqs cont -> return (Blocked reqs (f <$> cont))
      Blocked reqs1 cont1 -> do
        return (Blocked reqs1 (cont1 <*> Fetch fa))

instance Monad Fetch where
  return = pure
  Fetch m >>= k = Fetch $ \env -> do
    r <- m env
    case r of
      Done a -> unFetch (k a) env
      Blocked reqs cont -> return (Blocked reqs (cont >>= k))

-- ---------------------------------------------------------------------------
-- Environment

data Env = Env
  { envCache      :: IORef (Map String CachedResult)
  , envStatsRef   :: IORef Stats
  , envStateStore :: StateStore
  }

initEnv :: StateStore -> IO Env
initEnv ss = Env <$> newIORef Map.empty <*> newIORef emptyStats <*> pure ss

-- ---------------------------------------------------------------------------
-- Data fetching

-- | Issue a data fetch. The fetch will be batched with other fetches
-- in the same Applicative expression.
dataFetch :: forall r a. (DataSource r, DataSourceState r, Typeable a,
             Typeable r, Eq (r a), Hashable (r a), Show (r a), Show a)
          => r a -> Fetch a
dataFetch req = Fetch $ \env@Env{..} -> do
  let keyStr = makeCacheKeyStr req
  cache <- readIORef envCache
  case Map.lookup keyStr cache of
    Just (CachedResult rv) -> do
      case cast rv of
        Just (rv' :: ResultVar a) -> do
          result <- readResultVar rv'
          case result of
            Right a -> return (Done a)
            Left e -> throwIO e
        Nothing -> error "dataFetch: type mismatch in cache"
    Nothing -> do
      rv <- mkResultVar
      let entry = CachedResult rv
      modifyIORef' envCache (Map.insert keyStr entry)
      let bf = BlockedFetch req rv :: BlockedFetch r
          sbf = SomeBlockedFetch bf (typeRep (Proxy :: Proxy r))
      return (Blocked [sbf] (waitForResult rv))

-- | Pre-seed the cache with a known result for a request. Subsequent
-- dataFetch calls for the same request return the seeded value directly.
preFetch :: forall r a. (DataSource r, DataSourceState r, Typeable a,
            Typeable r, Eq (r a), Hashable (r a), Show (r a), Show a)
         => r a -> a -> Fetch ()
preFetch req val = Fetch $ \env@Env{..} -> do
  rv <- mkResultVar
  putSuccess rv val
  let keyStr = show (typeOf req) ++ ":" ++ show req
  modifyIORef' envCache (Map.insert keyStr (CachedResult rv))
  return (Done ())

-- | Create a fetch that waits for a result variable to be filled.
waitForResult :: Typeable a => ResultVar a -> Fetch a
waitForResult rv = Fetch $ \_ -> do
  result <- readResultVar rv
  case result of
    Right a -> return (Done a)
    Left e  -> throwIO e

-- ---------------------------------------------------------------------------
-- Running the fetch monad

-- | Run a Fetch computation, performing all data fetches.
runFetch :: Env -> Fetch a -> IO (a, Stats)
runFetch env (Fetch m) = do
  r <- m env
  case r of
    Done a -> do
      stats <- readIORef (envStatsRef env)
      return (a, stats)
    Blocked blocked cont -> do
      let grouped = groupByDataSource blocked

      mapM_ (dispatchGroup env) grouped

      let totalFetches = length grouped
      modifyIORef' (envStatsRef env) $ \stats ->
        stats { statsFetchRounds = statsFetchRounds stats + 1
              , statsFetchTotal = statsFetchTotal stats + totalFetches
              , statsBatchSizes = statsBatchSizes stats ++ [totalFetches]
              }

      runFetch env cont

-- | Group blocked fetches by their data source TypeRep.
groupByDataSource :: [SomeBlockedFetch] -> [(TypeRep, [SomeBlockedFetch])]
groupByDataSource = Map.toList . foldr go Map.empty
  where
    go sbf@(SomeBlockedFetch _ tr) = Map.insertWith (++) tr [sbf]

-- | Dispatch a group of fetches to a single data source.
dispatchGroup :: Env -> (TypeRep, [SomeBlockedFetch]) -> IO ()
dispatchGroup _ (_, []) = return ()
dispatchGroup env (_, sbfs) = do
  case head sbfs of
    SomeBlockedFetch (_ :: BlockedFetch r) _ -> do
      case stateGet (Proxy :: Proxy r) (envStateStore env) of
        Nothing ->
          mapM_ (\(SomeBlockedFetch (BlockedFetch _ rv) _) ->
            putFailure rv (userError "data source not initialized")) sbfs
        Just st -> do
          mapM_ (\(SomeBlockedFetch bf _) -> do
            let bf' = unsafeCoerce bf :: BlockedFetch r
            fetch st [bf']
            ) sbfs

-- ---------------------------------------------------------------------------
-- Combinators

-- | Fetch two values concurrently using Applicative batching.
pairFetch :: Fetch a -> Fetch b -> Fetch (a, b)
pairFetch fa fb = (,) <$> fa <*> fb

-- | Fetch multiple values concurrently.
traverseFetch :: [Fetch a] -> Fetch [a]
traverseFetch [] = pure []
traverseFetch (f:fs) = do
  x <- f
  xs <- traverseFetch fs
  return (x : xs)
