{-# LANGUAGE DataKinds        #-}
{-# LANGUAGE OverloadedLabels #-}
{-# LANGUAGE TypeApplications #-}
{-# LANGUAGE TypeOperators    #-}


module Main where

import Data.Functor.Identity
import ExtensibleRecord

------------------------------------------------------------------------
-- Helpers
------------------------------------------------------------------------

assertEqual :: (Eq a, Show a) => String -> a -> a -> IO ()
assertEqual name expected actual
  | expected == actual = putStrLn $ "PASS: " ++ name
  | otherwise = do
      putStrLn $ "FAIL: " ++ name
      putStrLn $ "  expected: " ++ show expected
      putStrLn $ "    actual: " ++ show actual
      error $ "Assertion failed: " ++ name

assertTrue :: String -> Bool -> IO ()
assertTrue name cond = assertEqual name True cond

------------------------------------------------------------------------
-- Tests
------------------------------------------------------------------------

main :: IO ()
main = do
    -- 1. nil + single insert + get
    let r1 = insert #name (Identity "Alice") nil
    assertEqual "insert+get single field"
      "Alice"
      (runIdentity (get #name r1))

    -- 2. Multiple inserts + gets
    let r2 = insert #age (Identity (30 :: Int))
           $ insert #name (Identity "Alice") nil
    assertEqual "get name from two-field record"
      "Alice"
      (runIdentity (get #name r2))
    assertEqual "get age from two-field record"
      30
      (runIdentity (get #age r2))

    -- 3. Three-field record
    let r3 = insert #z (Identity 'x')
           $ insert #y (Identity True)
           $ insert #x (Identity (1 :: Int)) nil
    assertEqual "three-field get x" 1    (runIdentity (get #x r3))
    assertEqual "three-field get y" True (runIdentity (get #y r3))
    assertEqual "three-field get z" 'x'  (runIdentity (get #z r3))

    -- 4. Update (same type)
    let r4 = update #name (Identity "Bob") r2
    assertEqual "update same type"
      "Bob"
      (runIdentity (get #name r4))
    assertEqual "update preserves other fields"
      30
      (runIdentity (get #age r4))

    -- 5. Update (change type: String -> Int)
    let r5 = update #name (Identity (42 :: Int)) r2
    assertEqual "update changes type"
      42
      (runIdentity (get #name r5))

    -- 6. Delete first field
    let r6 = delete #age r2
    assertEqual "delete first field, remaining get"
      "Alice"
      (runIdentity (get #name r6))

    -- 7. Delete middle field
    let r7 = delete #y r3
    assertEqual "delete middle - get x" 1   (runIdentity (get #x r7))
    assertEqual "delete middle - get z" 'x' (runIdentity (get #z r7))

    -- 8. Upsert (insert case: new key)
    let r8 = upsert #email (Identity "a@b.com") r2
    assertEqual "upsert insert new key"
      "a@b.com"
      (runIdentity (get #email r8))
    assertEqual "upsert insert preserves name"
      "Alice"
      (runIdentity (get #name r8))
    assertEqual "upsert insert preserves age"
      30
      (runIdentity (get #age r8))

    -- 9. Upsert (update case: existing key)
    let r9 = upsert #name (Identity "Charlie") r2
    assertEqual "upsert update existing"
      "Charlie"
      (runIdentity (get #name r9))
    assertEqual "upsert update preserves age"
      30
      (runIdentity (get #age r9))

    -- 10. Peel
    let (first, rest) = peel r2
    assertEqual "peel first element"
      30
      (runIdentity first)
    assertEqual "peel rest get"
      "Alice"
      (runIdentity (get #name rest))

    -- 11. Eq (equal)
    let ea = insert #x (Identity (1 :: Int)) nil
    let eb = insert #x (Identity (1 :: Int)) nil
    assertTrue "eq same records" (ea == eb)

    -- 12. Eq (not equal)
    let ec = insert #x (Identity (2 :: Int)) nil
    assertTrue "neq different records" (ea /= ec)

    -- 13. Eq (multi-field)
    let ed = insert #b (Identity True) $ insert #a (Identity (1 :: Int)) nil
    let ee = insert #b (Identity True) $ insert #a (Identity (1 :: Int)) nil
    let ef = insert #b (Identity False) $ insert #a (Identity (1 :: Int)) nil
    assertTrue "eq multi-field same" (ed == ee)
    assertTrue "neq multi-field diff" (ed /= ef)

    -- 14. Merge
    let left  = insert #a (Identity (1 :: Int)) nil
    let right = insert #b (Identity True) nil
    let merged = merge left right
    assertEqual "merge get left field"
      1
      (runIdentity (get #a merged))
    assertEqual "merge get right field"
      True
      (runIdentity (get #b merged))

    -- 15. Merge larger
    let ml = insert #y (Identity "hi") $ insert #x (Identity (10 :: Int)) nil
    let mr = insert #w (Identity 'z') $ insert #v (Identity False) nil
    let mm = merge ml mr
    assertEqual "merge4 get x" 10    (runIdentity (get #x mm))
    assertEqual "merge4 get y" "hi"  (runIdentity (get #y mm))
    assertEqual "merge4 get v" False (runIdentity (get #v mm))
    assertEqual "merge4 get w" 'z'   (runIdentity (get #w mm))

    putStrLn "ALL TESTS PASSED"
