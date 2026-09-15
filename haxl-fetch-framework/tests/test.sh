#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

cd /app

# Write the test driver that exercises MicroHaxl
cat > /app/TestDriver.hs << 'HASKELL_EOF'
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

module Main where

import MicroHaxl
import Control.Concurrent
import Control.Exception (SomeException, try, evaluate, toException)
import Data.IORef
import Data.Typeable
import Data.Hashable
import Data.Proxy
import qualified Data.Map.Strict as Map
import System.Exit
import System.IO
import Data.Time.Clock.POSIX (getPOSIXTime)

-- =========================================================================
-- Mock Data Source: KeyValue store
-- =========================================================================

data KVReq a where
  GetKey :: String -> KVReq String
  deriving (Typeable)

deriving instance Show (KVReq a)
deriving instance Eq (KVReq a)

instance Hashable (KVReq a) where
  hashWithSalt s (GetKey k) = hashWithSalt s (0 :: Int, k)

-- NOTE: Helper with explicit type signature avoids GHC "untouchable"
-- type variable error when GADT constructors are matched inside mapM_.
fetchKV :: IORef (Map.Map String String) -> BlockedFetch KVReq -> IO ()
fetchKV ref (BlockedFetch (GetKey k) rv) = do
  store <- readIORef ref
  case Map.lookup k store of
    Just v  -> putSuccess rv v
    Nothing -> putFailure rv (userError $ "key not found: " ++ k)

instance DataSource KVReq where
  dataSourceName _ = "KeyValue"
  fetch st bfs = case st of
    KVState ref logRef -> do
      modifyIORef' logRef (\xs -> length bfs : xs)
      mapM_ (fetchKV ref) bfs

instance DataSourceState KVReq where
  data SourceState KVReq = KVState (IORef (Map.Map String String)) (IORef [Int])

-- =========================================================================
-- Mock Data Source: Counter
-- =========================================================================

data CounterReq a where
  GetCount :: String -> CounterReq Int
  deriving (Typeable)

deriving instance Show (CounterReq a)
deriving instance Eq (CounterReq a)

instance Hashable (CounterReq a) where
  hashWithSalt s (GetCount k) = hashWithSalt s (1 :: Int, k)

fetchCounter :: IORef (Map.Map String Int) -> BlockedFetch CounterReq -> IO ()
fetchCounter ref (BlockedFetch (GetCount k) rv) = do
  counts <- readIORef ref
  let c = Map.findWithDefault 0 k counts
  modifyIORef' ref (Map.insertWith (+) k 1)
  putSuccess rv c

instance DataSource CounterReq where
  dataSourceName _ = "Counter"
  fetch st bfs = case st of
    CounterState ref -> mapM_ (fetchCounter ref) bfs

instance DataSourceState CounterReq where
  data SourceState CounterReq = CounterState (IORef (Map.Map String Int))

-- =========================================================================
-- Mock Data Source: Slow (for concurrency testing)
-- =========================================================================

data SlowReq a where
  SlowGet :: String -> SlowReq String
  deriving (Typeable)

deriving instance Show (SlowReq a)
deriving instance Eq (SlowReq a)

instance Hashable (SlowReq a) where
  hashWithSalt s (SlowGet k) = hashWithSalt s (2 :: Int, k)

fetchSlow :: BlockedFetch SlowReq -> IO ()
fetchSlow (BlockedFetch (SlowGet k) rv) = putSuccess rv ("slow:" ++ k)

instance DataSource SlowReq where
  dataSourceName _ = "Slow"
  fetch st bfs = case st of
    SlowState delay -> do
      threadDelay delay
      mapM_ fetchSlow bfs

instance DataSourceState SlowReq where
  data SourceState SlowReq = SlowState Int

-- =========================================================================
-- Mock Data Source: Failing
-- =========================================================================

data FailReq a where
  FailGet :: String -> FailReq String
  deriving (Typeable)

deriving instance Show (FailReq a)
deriving instance Eq (FailReq a)

instance Hashable (FailReq a) where
  hashWithSalt s (FailGet k) = hashWithSalt s (3 :: Int, k)

instance DataSource FailReq where
  dataSourceName _ = "Failing"
  fetch _ _ = error "data source crashed!"

instance DataSourceState FailReq where
  data SourceState FailReq = FailState

-- =========================================================================
-- Test harness
-- =========================================================================

data TestResult = Pass String | Fail String String

runTest :: String -> IO TestResult -> IO TestResult
runTest name action = do
  result <- try action
  case result of
    Left (e :: SomeException) -> return $ Fail name (show e)
    Right r -> return r

assertEqual :: (Eq a, Show a) => String -> a -> a -> IO TestResult
assertEqual name expected actual
  | expected == actual = return $ Pass name
  | otherwise = return $ Fail name $
      "expected " ++ show expected ++ " but got " ++ show actual

assertBool :: String -> Bool -> String -> IO TestResult
assertBool name cond msg
  | cond = return $ Pass name
  | otherwise = return $ Fail name msg

-- =========================================================================
-- Helper to build environments
-- =========================================================================

mkKVEnv :: [(String, String)] -> IO (Env, IORef [Int])
mkKVEnv pairs = do
  storeRef <- newIORef (Map.fromList pairs)
  logRef <- newIORef []
  let ss = stateSet (Proxy :: Proxy KVReq) (KVState storeRef logRef) emptyStateStore
  env <- initEnv ss
  return (env, logRef)

mkMultiEnv :: [(String, String)] -> IO (Env, IORef [Int])
mkMultiEnv pairs = do
  storeRef <- newIORef (Map.fromList pairs)
  logRef <- newIORef []
  counterRef <- newIORef Map.empty
  let ss = stateSet (Proxy :: Proxy KVReq) (KVState storeRef logRef)
         $ stateSet (Proxy :: Proxy CounterReq) (CounterState counterRef)
         $ stateSet (Proxy :: Proxy SlowReq) (SlowState 100000)
         $ stateSet (Proxy :: Proxy FailReq) FailState
         $ emptyStateStore
  env <- initEnv ss
  return (env, logRef)

-- =========================================================================
-- Tests
-- =========================================================================

test_single_fetch :: IO TestResult
test_single_fetch = runTest "single_fetch" $ do
  (env, _) <- mkKVEnv [("hello", "world")]
  (result, stats) <- runFetch env (dataFetch (GetKey "hello"))
  r1 <- assertEqual "single_fetch_value" "world" result
  case r1 of
    Fail _ _ -> return r1
    Pass _ -> assertEqual "single_fetch" 1 (statsFetchRounds stats)

test_applicative_batching :: IO TestResult
test_applicative_batching = runTest "applicative_batching" $ do
  (env, logRef) <- mkKVEnv [("a", "1"), ("b", "2")]
  let comp = pairFetch (dataFetch (GetKey "a")) (dataFetch (GetKey "b"))
  ((r1, r2), stats) <- runFetch env comp
  v <- assertEqual "batch_values" ("1", "2") (r1, r2)
  case v of
    Fail _ _ -> return v
    Pass _ -> do
      r <- assertEqual "applicative_batching" 1 (statsFetchRounds stats)
      case r of
        Fail _ _ -> return r
        Pass _ -> do
          batches <- readIORef logRef
          assertEqual "applicative_batching" [2] batches

test_monadic_sequencing :: IO TestResult
test_monadic_sequencing = runTest "monadic_sequencing" $ do
  (env, _) <- mkKVEnv [("a", "1"), ("b", "2")]
  let comp = do
        r1 <- dataFetch (GetKey "a")
        r2 <- dataFetch (GetKey "b")
        return (r1, r2)
  ((r1, r2), stats) <- runFetch env comp
  v <- assertEqual "seq_values" ("1", "2") (r1, r2)
  case v of
    Fail _ _ -> return v
    Pass _ -> assertEqual "monadic_sequencing" 2 (statsFetchRounds stats)

test_deduplication :: IO TestResult
test_deduplication = runTest "deduplication" $ do
  (env, logRef) <- mkKVEnv [("x", "42")]
  let comp = pairFetch (dataFetch (GetKey "x")) (dataFetch (GetKey "x"))
  ((r1, r2), stats) <- runFetch env comp
  v <- assertEqual "dedup_values" ("42", "42") (r1, r2)
  case v of
    Fail _ _ -> return v
    Pass _ -> do
      r <- assertEqual "dedup_total" 1 (statsFetchTotal stats)
      case r of
        Fail _ _ -> return r
        Pass _ -> do
          batches <- readIORef logRef
          assertEqual "deduplication" [1] batches

test_traverse_batching :: IO TestResult
test_traverse_batching = runTest "traverse_batching" $ do
  (env, logRef) <- mkKVEnv [("k1","v1"), ("k2","v2"), ("k3","v3")]
  let comp = traverseFetch
        [ dataFetch (GetKey "k1")
        , dataFetch (GetKey "k2")
        , dataFetch (GetKey "k3")
        ]
  (results, stats) <- runFetch env comp
  v <- assertEqual "traverse_values" ["v1","v2","v3"] results
  case v of
    Fail _ _ -> return v
    Pass _ -> do
      r <- assertEqual "traverse_batching" 1 (statsFetchRounds stats)
      case r of
        Fail _ _ -> return r
        Pass _ -> do
          batches <- readIORef logRef
          assertEqual "traverse_batching" [3] batches

test_stats_accuracy :: IO TestResult
test_stats_accuracy = runTest "stats_accuracy" $ do
  (env, _) <- mkMultiEnv [("a","1"), ("b","2")]
  let comp = pairFetch
        (pairFetch (dataFetch (GetKey "a")) (dataFetch (GetKey "b")))
        (dataFetch (GetCount "c"))
  (((va, vb), vc), stats) <- runFetch env comp
  r1 <- assertEqual "stats_rounds" 1 (statsFetchRounds stats)
  case r1 of
    Fail _ _ -> return r1
    Pass _ -> do
      r2 <- assertEqual "stats_total" 3 (statsFetchTotal stats)
      case r2 of
        Fail _ _ -> return r2
        Pass _ -> do
          let dsMap = statsDatasources stats
          r3 <- assertEqual "stats_kv" (Just 2) (Map.lookup "KeyValue" dsMap)
          case r3 of
            Fail _ _ -> return r3
            Pass _ -> assertEqual "stats_accuracy" (Just 1) (Map.lookup "Counter" dsMap)

test_cross_type_cache :: IO TestResult
test_cross_type_cache = runTest "cross_type_cache" $ do
  (env, _) <- mkMultiEnv [("x", "hello")]
  let comp = pairFetch (dataFetch (GetKey "x")) (dataFetch (GetCount "x"))
  ((s, i), _) <- runFetch env comp
  r1 <- assertEqual "cross_type_string" "hello" s
  case r1 of
    Fail _ _ -> return r1
    Pass _ -> assertEqual "cross_type_cache" 0 i

test_exception_propagation :: IO TestResult
test_exception_propagation = runTest "exception_propagation" $ do
  (env, _) <- mkMultiEnv []
  let comp = dataFetch (FailGet "x")
  result <- try $ runFetch env comp :: IO (Either SomeException (String, Stats))
  case result of
    Left _ -> return $ Pass "exception_propagation"
    Right _ -> return $ Fail "exception_propagation"
      "expected exception but got success"

test_concurrent_dispatch :: IO TestResult
test_concurrent_dispatch = runTest "concurrent_dispatch" $ do
  slowRef <- newIORef (Map.fromList [("s","val")])
  logRef <- newIORef []
  let ss = stateSet (Proxy :: Proxy KVReq) (KVState slowRef logRef)
         $ stateSet (Proxy :: Proxy SlowReq) (SlowState 100000)
         $ emptyStateStore
  env <- initEnv ss
  let comp = pairFetch (dataFetch (GetKey "s")) (dataFetch (SlowGet "t"))
  t0 <- getPOSIXTime
  ((r1, r2), _) <- runFetch env comp
  t1 <- getPOSIXTime
  let elapsed_ms = realToFrac (t1 - t0) * 1000 :: Double
  v <- assertEqual "concurrent_values" ("val", "slow:t") (r1, r2)
  case v of
    Fail _ _ -> return v
    Pass _ ->
      assertBool "concurrent_dispatch" (elapsed_ms < 300)
        ("took " ++ show elapsed_ms ++ "ms, expected < 300ms for concurrent dispatch")

test_multi_round :: IO TestResult
test_multi_round = runTest "multi_round" $ do
  (env, _) <- mkKVEnv [("a","b"), ("b","c"), ("c","done")]
  let comp = do
        (va, vc) <- pairFetch (dataFetch (GetKey "a")) (dataFetch (GetKey "c"))
        vb <- dataFetch (GetKey va)
        return (va, vb, vc)
  ((r1, r2, r3), stats) <- runFetch env comp
  v <- assertEqual "multi_round_values" ("b", "c", "done") (r1, r2, r3)
  case v of
    Fail _ _ -> return v
    Pass _ -> assertEqual "multi_round" 2 (statsFetchRounds stats)

test_prefetch :: IO TestResult
test_prefetch = runTest "prefetch" $ do
  (env, logRef) <- mkKVEnv [("a", "real_value")]
  let comp = do
        preFetch (GetKey "a") "cached"
        dataFetch (GetKey "a")
  (result, stats) <- runFetch env comp
  v <- assertEqual "prefetch_value" "cached" result
  case v of
    Fail _ _ -> return v
    Pass _ -> do
      r <- assertEqual "prefetch_rounds" 0 (statsFetchRounds stats)
      case r of
        Fail _ _ -> return r
        Pass _ -> do
          batches <- readIORef logRef
          assertEqual "prefetch" [] batches

-- =========================================================================
-- Main
-- =========================================================================

main :: IO ()
main = do
  hSetBuffering stdout LineBuffering
  results <- sequence
    [ test_single_fetch
    , test_applicative_batching
    , test_monadic_sequencing
    , test_deduplication
    , test_traverse_batching
    , test_stats_accuracy
    , test_cross_type_cache
    , test_exception_propagation
    , test_concurrent_dispatch
    , test_multi_round
    , test_prefetch
    ]

  let passes = length [() | Pass _ <- results]
      fails  = length [() | Fail _ _ <- results]
      total  = length results

  mapM_ printResult results
  putStrLn $ "\n" ++ show passes ++ "/" ++ show total ++ " tests passed"

  if fails > 0
    then exitWith (ExitFailure 1)
    else exitSuccess

printResult :: TestResult -> IO ()
printResult (Pass name) = putStrLn $ "PASS: " ++ name
printResult (Fail name msg) = putStrLn $ "FAIL: " ++ name ++ " - " ++ msg
HASKELL_EOF

echo "Compiling MicroHaxl + TestDriver..."
ghc -O0 -o /app/test_runner /app/TestDriver.hs /app/MicroHaxl.hs \
  -no-keep-hi-files -no-keep-o-files 2>&1
COMPILE_RC=$?

if [ $COMPILE_RC -ne 0 ]; then
  echo "COMPILATION FAILED"
else
  echo "Running tests..."
  timeout 60 /app/test_runner 2>&1 || true
fi

# Run pytest verification
cd /tests
python3 -m pytest /tests/test_state.py -v 2>&1
PYTEST_RC=$?

mkdir -p /logs/verifier
if [ $PYTEST_RC -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_RC
