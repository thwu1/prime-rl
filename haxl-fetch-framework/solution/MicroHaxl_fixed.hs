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


module MicroHaxl
  ( Fetch(..)
  , Result(..)
  , BlockedFetch(..)
  , ResultVar
  , mkResultVar
  , putResult
  , putFailure
  , putSuccess

  , DataSource(..)
  , DataSourceState(..)

  , Env(..)
  , initEnv

  , runFetch

  , Stats(..)
  , emptyStats

  , CacheKey(..)

  , dataFetch
  , preFetch

  , pairFetch
  , traverseFetch

  , StateStore
  , emptyStateStore
  , stateSet
  , stateGet
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

newtype ResultVar a = ResultVar (MVar (Either SomeException a))

mkResultVar :: IO (ResultVar a)
mkResultVar = ResultVar <$> newEmptyMVar

putResult :: ResultVar a -> Either SomeException a -> IO ()
putResult (ResultVar mv) r = do
  _ <- tryPutMVar mv r
  return ()

putFailure :: Exception e => ResultVar a -> e -> IO ()
putFailure rv e = putResult rv (Left (toException e))

putSuccess :: ResultVar a -> a -> IO ()
putSuccess rv a = putResult rv (Right a)

readResultVar :: ResultVar a -> IO (Either SomeException a)
readResultVar (ResultVar mv) = readMVar mv

-- ---------------------------------------------------------------------------
-- Blocked fetches

data BlockedFetch r = forall a. (Typeable a, Show a) =>
  BlockedFetch (r a) (ResultVar a)

-- ---------------------------------------------------------------------------
-- DataSource class

class (Typeable r) => DataSource r where
  dataSourceName :: r a -> String
  fetch :: SourceState r -> [BlockedFetch r] -> IO ()

class Typeable r => DataSourceState r where
  data SourceState r

-- ---------------------------------------------------------------------------
-- State Store (heterogeneous, keyed by TypeRep)

data SomeState = forall r. (DataSource r, DataSourceState r) =>
  SomeState (SourceState r)

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

data CacheKey = forall r a. (DataSource r, Typeable a, Typeable r,
  Eq (r a), Hashable (r a), Show (r a)) =>
  CacheKey TypeRep (r a)

data CachedResult = forall a. Typeable a => CachedResult (ResultVar a)

makeCacheKeyStr :: (Typeable r, Typeable a, Show (r a)) => r a -> String
makeCacheKeyStr req = show (typeOf req) ++ "::" ++ show req

-- ---------------------------------------------------------------------------
-- Stats

data Stats = Stats
  { statsFetchRounds :: !Int
  , statsFetchTotal  :: !Int
  , statsBatchSizes  :: [Int]
  , statsDatasources :: Map String Int
  } deriving (Show, Eq)

emptyStats :: Stats
emptyStats = Stats 0 0 [] Map.empty

-- ---------------------------------------------------------------------------
-- The Fetch monad

data Result a
  = Done a
  | forall b. Blocked [SomeBlockedFetch] (Fetch a)

data SomeBlockedFetch = forall r. (DataSource r, DataSourceState r) =>
  SomeBlockedFetch (BlockedFetch r) TypeRep

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
        ra <- fa env
        case ra of
          Done a -> return (Blocked reqs1 (fmap ($ a) cont1))
          Blocked reqs2 cont2 ->
            return (Blocked (reqs1 ++ reqs2) (cont1 <*> cont2))

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

dataFetch :: forall r a. (DataSource r, DataSourceState r, Typeable a, Typeable r,
             Eq (r a), Hashable (r a), Show (r a), Show a) => r a -> Fetch a
dataFetch req = Fetch $ \env@Env{..} -> do
  let keyStr = makeCacheKeyStr req
  cache <- readIORef envCache
  case Map.lookup keyStr cache of
    Just (CachedResult rv) -> do
      case cast rv of
        Just (rv' :: ResultVar a) -> do
          let ResultVar mv = rv'
          maybeResult <- tryReadMVar mv
          case maybeResult of
            Just (Right a) -> return (Done a)
            Just (Left e)  -> throwIO e
            Nothing -> return (Blocked [] (waitForResult rv'))
        Nothing -> error "dataFetch: type mismatch in cache"
    Nothing -> do
      rv <- mkResultVar
      let entry = CachedResult rv
      modifyIORef' envCache (Map.insert keyStr entry)
      let bf = BlockedFetch req rv :: BlockedFetch r
          sbf = SomeBlockedFetch bf (typeRep (Proxy :: Proxy r))
      return (Blocked [sbf] (waitForResult rv))

preFetch :: forall r a. (DataSource r, DataSourceState r, Typeable a,
            Typeable r, Eq (r a), Hashable (r a), Show (r a), Show a)
         => r a -> a -> Fetch ()
preFetch req val = Fetch $ \env@Env{..} -> do
  rv <- mkResultVar
  putSuccess rv val
  let keyStr = makeCacheKeyStr req
  modifyIORef' envCache (Map.insert keyStr (CachedResult rv))
  return (Done ())

waitForResult :: Typeable a => ResultVar a -> Fetch a
waitForResult rv = Fetch $ \_ -> do
  result <- readResultVar rv
  case result of
    Right a -> return (Done a)
    Left e  -> throwIO e

-- ---------------------------------------------------------------------------
-- Running the fetch monad

runFetch :: Env -> Fetch a -> IO (a, Stats)
runFetch env (Fetch m) = do
  r <- m env
  case r of
    Done a -> do
      stats <- readIORef (envStatsRef env)
      return (a, stats)
    Blocked blocked cont -> do
      let grouped = groupByDataSource blocked

      if null blocked
        then
          runFetch env cont
        else do
          dispatchAllConcurrently env grouped

          let totalFetches = length blocked
              dsStats = foldr (\(_, sbfs) acc ->
                case sbfs of
                  [] -> acc
                  (SomeBlockedFetch (BlockedFetch req _) _ : _) ->
                    Map.insertWith (+) (dataSourceName req) (length sbfs) acc
                ) Map.empty grouped

          modifyIORef' (envStatsRef env) $ \stats ->
            stats { statsFetchRounds = statsFetchRounds stats + 1
                  , statsFetchTotal = statsFetchTotal stats + totalFetches
                  , statsBatchSizes = statsBatchSizes stats ++ [totalFetches]
                  , statsDatasources = Map.unionWith (+) (statsDatasources stats) dsStats
                  }

          runFetch env cont

groupByDataSource :: [SomeBlockedFetch] -> [(TypeRep, [SomeBlockedFetch])]
groupByDataSource = Map.toList . foldr go Map.empty
  where
    go sbf@(SomeBlockedFetch _ tr) = Map.insertWith (++) tr [sbf]

dispatchAllConcurrently :: Env -> [(TypeRep, [SomeBlockedFetch])] -> IO ()
dispatchAllConcurrently env groups = do
  doneVars <- mapM (\g -> do
    done <- newEmptyMVar
    _ <- forkIO $ do
      dispatchGroup env g `catch` \(e :: SomeException) -> do
        let (_, sbfs) = g
        mapM_ (\(SomeBlockedFetch (BlockedFetch _ rv) _) ->
          putResult rv (Left e)) sbfs
      putMVar done ()
    return done
    ) groups
  mapM_ takeMVar doneVars

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
          let bfs = map (\(SomeBlockedFetch bf _) ->
                unsafeCoerce bf :: BlockedFetch r) sbfs
          fetch st bfs `catch` \(e :: SomeException) ->
            mapM_ (\(SomeBlockedFetch (BlockedFetch _ rv) _) ->
              putResult rv (Left e)) sbfs

-- ---------------------------------------------------------------------------
-- Combinators

pairFetch :: Fetch a -> Fetch b -> Fetch (a, b)
pairFetch fa fb = (,) <$> fa <*> fb

traverseFetch :: [Fetch a] -> Fetch [a]
traverseFetch [] = pure []
traverseFetch (f:fs) = (:) <$> f <*> traverseFetch fs
