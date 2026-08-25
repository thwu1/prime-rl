# OptimBench valid-1486 archive

This is a portable, dereferenced archive of the exact 1,486-task Harbor bank used by the historical Kimi K2.6 MiniSWE evaluation:

`/checkpoint/ram-h100-2/tianhaowu/harbor_tasks/optimbench-valid-1486`

The archive contains 45 ordered parts totaling 4,407,291,599 bytes. Parts `0000` through `0043` are 99,999,999 bytes each; part `0044` is 7,291,643 bytes. The SHA-256 of the concatenated zstd stream is:

`e3b646e238b0ae358e411a6c3e32868c6c8ef038268ef425455c43200609cc4f`

Verify the downloaded parts:

```bash
sha256sum -c SHA256SUMS
```

Extract without creating an intermediate monolithic archive:

```bash
mkdir -p DESTINATION
cat optimbench-valid-1486.tar.zst.part-*.part \
  | zstd --long=27 -dc \
  | tar -xpf - -C DESTINATION
```

The extracted top-level directory is `optimbench-valid-1486`.

The source symlinks were dereferenced during archival. The complete stream was validated by decompressing it and listing the full tar archive before publication.
