#!/usr/bin/env python3

"""Write ground-truth annotated Dafny programs to /app/."""

import os

SEL_SORT = r'''predicate sorted_seg(a:array<int>, i:int, j:int) //j not included
requires 0 <= i <= j <= a.Length
reads a
{
    forall l, k :: i <= l <= k < j ==> a[l] <= a[k]
}


method selSort (a:array<int>, c:int, f:int)//f excluded
modifies a
requires 0 <= c <= f <= a.Length //when c==f empty sequence
ensures sorted_seg(a,c,f)
ensures multiset(a[c..f]) == old(multiset(a[c..f]))
ensures a[..c]==old(a[..c]) && a[f..]==old(a[f..])
 {if (c<=f-1){//two elements at least
  var i:=c;
  while (i<f-1) //outer loop
     decreases f-i
    invariant c<=i<=f
    invariant sorted_seg(a,c,i)
    invariant forall k,l::c<=k<i && i<=l<f ==> a[k]<=a[l]
    invariant multiset(a[c..f]) == old(multiset(a[c..f]))
    invariant a[..c]==old(a[..c]) && a[f..]==old(a[f..])
  {
   var less:=i;
   var j:=i+1;
   while (j<f) //inner loop
    decreases f-j
    invariant i+1<=j<=f
    invariant i<=less<f
    invariant sorted_seg(a,c,i)
    invariant forall k::i<=k<j ==> a[less] <= a[k]
    invariant forall k,l::c<=k<i && i<=l<f ==> a[k]<=a[l]
    invariant multiset(a[c..f]) == old(multiset(a[c..f]))
    invariant a[..c]==old(a[..c]) && a[f..]==old(a[f..])

    { if (a[j]<a[less]) {less:=j;}
      j:=j+1;
    }
   a[i],a[less]:=a[less],a[i];
   i:=i+1;
  }
 }
 }
'''

INSERTION_SORT = r'''predicate sorted_seg(a:array<int>, i:int, j:int) //i and j included
requires 0 <= i <= j+1 <= a.Length
reads a
{
    forall l, k :: i <= l <= k <= j ==> a[l] <= a[k]
}

method InsertionSort(a: array<int>)
  modifies a;
  ensures sorted_seg(a,0,a.Length-1)
  ensures multiset(a[..]) == old(multiset(a[..]))
{

  var i := 0;
  assert multiset(a[..]) == old(multiset(a[..]));
  while (i < a.Length)
     decreases a.Length-i
     invariant 0<=i<=a.Length
     invariant sorted_seg(a,0,i-1)
     invariant multiset(a[..]) == old(multiset(a[..]))
    invariant forall k::i<k<a.Length ==> a[k] == old(a[k])
  {

     var temp := a[i];
     var j := i;
     while (j > 0 && temp < a[j - 1])
         decreases j
         invariant 0<=j<=i
         invariant sorted_seg(a,0,j-1) && sorted_seg(a,j+1,i)
         invariant forall k,l :: 0<=k<=j-1 && j+1<=l<=i ==> a[k]<=a[l]
         invariant forall k :: j<k<=i ==> temp <a[k]
         invariant forall k::i<k<a.Length ==> a[k] == old(a[k])
         invariant multiset(a[..]) - multiset{a[j]} + multiset{temp} == old(multiset(a[..]))
     {

         a[j] := a[j - 1];
         j := j - 1;
     }


  a[j] := temp;
  i := i + 1;

  }
}
'''

SEQ_MAX_SUM = r'''function Sum(v:array<int>,i:int,j:int):int
reads v
requires 0<=i<=j<=v.Length
decreases j
{
    if (i==j) then 0
    else Sum(v,i,j-1)+v[j-1]
}

predicate SumMaxToRight(v:array<int>,i:int,s:int)
reads v
requires 0<=i<v.Length
{
forall l,ss {:induction l}::0<=l<=i && ss==i+1==> Sum(v,l,ss)<=s
}

method segMaxSum(v:array<int>,i:int) returns (s:int,k:int)
requires v.Length>0 && 0<=i<v.Length
ensures 0<=k<=i && s==Sum(v,k,i+1) &&  SumMaxToRight(v,i,s)
{
 s:=v[0];
 k:=0;
 var j:=0;
 while (j<i)
 decreases i-j
 invariant 0<=j<=i
 invariant 0<=k<=j && s==Sum(v,k,j+1)
 invariant SumMaxToRight(v,j,s)
 {
    if (s+v[j+1]>v[j+1]) {s:=s+v[j+1];}
    else {k:=j+1;s:=v[j+1];}

     j:=j+1;
 }

}


function Sum2(v:array<int>,i:int,j:int):int
reads v
requires 0<=i<=j<=v.Length
decreases j-i
{
    if (i==j) then 0
    else v[i]+Sum2(v,i+1,j)
}

//Now do the same but with a loop from right to left
predicate SumMaxToRight2(v:array<int>,j:int,i:int,s:int)//maximum sum stuck to the right
reads v
requires 0<=j<=i<v.Length
{(forall l,ss {:induction l}::j<=l<=i && ss==i+1 ==> Sum2(v,l,ss)<=s)}

method segSumaMaxima2(v:array<int>,i:int) returns (s:int,k:int)
requires v.Length>0 && 0<=i<v.Length
ensures 0<=k<=i && s==Sum2(v,k,i+1) &&  SumMaxToRight2(v,0,i,s)
//Implement and verify
{
 s:=v[i];
 k:=i;
 var j:=i;
 var maxs:=s;
 while(j>0)
 decreases j
 invariant 0<=j<=i
 invariant 0<=k<=i
 invariant s==Sum2(v,j,i+1)
 invariant SumMaxToRight2(v,j,i,maxs)
 invariant maxs==Sum2(v,k,i+1)
 {
    s:=s+v[j-1];
    if(s>maxs){
        maxs:=s;
        k:=j-1;
    }
    j:=j-1;
 }
 s:=maxs;
}
'''


def main():
    programs = {
        "sel_sort.dfy": SEL_SORT,
        "insertion_sort.dfy": INSERTION_SORT,
        "seq_max_sum.dfy": SEQ_MAX_SUM,
    }
    for name, content in programs.items():
        path = os.path.join("/app", name)
        with open(path, "w") as f:
            f.write(content)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
