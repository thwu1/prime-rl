#!/usr/bin/env bash
set -euo pipefail
umask 077

required=(
    QWEN_TRACE_PACKAGE_PROJECT_DIR
    QWEN_TRACE_PACKAGE_EXPECTED_REVISION
    QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS
    QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS_SHA256
    QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS
    QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS_SHA256
    QWEN_TRACE_PACKAGE_CERTIFICATE
    QWEN_TRACE_PACKAGE_CERTIFICATE_SHA256
    QWEN_TRACE_PACKAGE_OUTPUT_DIR
)
for variable in "${required[@]}"; do
    [[ -n ${!variable:-} ]] || { printf '{"code":"required_environment_missing","state":"error"}\n'; exit 2; }
done

project=$(realpath -e -- "$QWEN_TRACE_PACKAGE_PROJECT_DIR")
output=$QWEN_TRACE_PACKAGE_OUTPUT_DIR
chunk_bytes=${QWEN_TRACE_PACKAGE_CHUNK_BYTES:-95000000}
compression_level=${QWEN_TRACE_PACKAGE_ZSTD_LEVEL:-15}
[[ $QWEN_TRACE_PACKAGE_EXPECTED_REVISION =~ ^[0-9a-f]{40}$ \
    && "$(git -C "$project" rev-parse HEAD)" == "$QWEN_TRACE_PACKAGE_EXPECTED_REVISION" \
    && -z "$(git -C "$project" status --porcelain=v1 --untracked-files=all)" ]] \
    || { printf '{"code":"project_identity_invalid","state":"error"}\n'; exit 2; }
[[ $output == /* && $chunk_bytes =~ ^[1-9][0-9]*$ && $chunk_bytes -lt 100000000 \
    && $compression_level =~ ^[1-9][0-9]*$ && $compression_level -le 19 ]] \
    || { printf '{"code":"package_configuration_invalid","state":"error"}\n'; exit 2; }
[[ ! -e $output && ! -L $output ]] \
    || { printf '{"code":"output_exists","state":"error"}\n'; exit 2; }
output_parent=$(realpath -e -- "$(dirname -- "$output")")
[[ $output == "$output_parent/$(basename -- "$output")" ]] \
    || { printf '{"code":"output_path_invalid","state":"error"}\n'; exit 2; }

inputs=(
    "$QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS:$QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS_SHA256"
    "$QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS:$QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS_SHA256"
    "$QWEN_TRACE_PACKAGE_CERTIFICATE:$QWEN_TRACE_PACKAGE_CERTIFICATE_SHA256"
)
for binding in "${inputs[@]}"; do
    path=${binding%:*}
    digest=${binding##*:}
    [[ $path == /* && $digest =~ ^[0-9a-f]{64}$ && -f $path && ! -L $path \
        && "$(sha256sum "$path" | cut -d' ' -f1)" == "$digest" ]] \
        || { printf '{"code":"input_artifact_invalid","state":"error"}\n'; exit 2; }
done

temporary=$(mktemp -d "$output_parent/.$(basename -- "$output").XXXXXXXX")
chmod 0700 "$temporary"
published=0
cleanup() {
    if [[ $published == 0 && -d $temporary ]]; then
        rm -rf -- "$temporary"
    fi
}
trap cleanup EXIT INT TERM

archive="$temporary/qwen-2499-unfiltered-trajectories.tar.zst"
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
original_relative=${QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS#"$eval_root/"}
continuation_relative=${QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS#"$eval_root/"}
certificate_relative=${QWEN_TRACE_PACKAGE_CERTIFICATE#"$eval_root/"}
[[ $original_relative != "$QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS" \
    && $continuation_relative != "$QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS" \
    && $certificate_relative != "$QWEN_TRACE_PACKAGE_CERTIFICATE" ]] \
    || { printf '{"code":"input_boundary_invalid","state":"error"}\n'; exit 2; }

tar --format=posix --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -C "$eval_root" -cf - \
    "$original_relative" "$continuation_relative" "$certificate_relative" \
    | zstd -q -T4 -"$compression_level" -o "$archive"
archive_bytes=$(stat -c %s "$archive")
archive_sha256=$(sha256sum "$archive" | cut -d' ' -f1)

mkdir -m 700 "$temporary/chunks"
split -b "$chunk_bytes" -d -a 3 --additional-suffix=.part \
    "$archive" "$temporary/chunks/qwen-2499-unfiltered-trajectories.tar.zst."
chunks_jsonl="$temporary/chunks.jsonl"
for chunk in "$temporary"/chunks/*; do
    name=$(basename -- "$chunk")
    bytes=$(stat -c %s "$chunk")
    digest=$(sha256sum "$chunk" | cut -d' ' -f1)
    jq -nc --arg name "$name" --arg sha256 "$digest" --argjson bytes "$bytes" \
        '{name:$name,bytes:$bytes,sha256:$sha256}' >>"$chunks_jsonl"
done
chmod 0600 "$chunks_jsonl"

chunks=$(jq -sc '.' "$chunks_jsonl")
jq -n \
    --arg archive_sha256 "$archive_sha256" \
    --argjson archive_bytes "$archive_bytes" \
    --argjson chunk_bytes "$chunk_bytes" \
    --argjson chunks "$chunks" \
    --arg original_results_sha256 "$QWEN_TRACE_PACKAGE_ORIGINAL_RESULTS_SHA256" \
    --arg continuation_results_sha256 "$QWEN_TRACE_PACKAGE_CONTINUATION_RESULTS_SHA256" \
    --arg certificate_sha256 "$QWEN_TRACE_PACKAGE_CERTIFICATE_SHA256" \
    --arg project_revision "$QWEN_TRACE_PACKAGE_EXPECTED_REVISION" \
    '{
      schema_version:1,
      kind:"qwen-2499-unfiltered-trajectory-package",
      compression:"zstd",
      archive:{bytes:$archive_bytes,sha256:$archive_sha256},
      chunk_bytes:$chunk_bytes,
      chunks:$chunks,
      inputs:{
        original_results_sha256:$original_results_sha256,
        continuation_results_sha256:$continuation_results_sha256,
        continuation_certificate_sha256:$certificate_sha256
      },
      project_revision:$project_revision
    }' >"$temporary/manifest.json"
chmod 0600 "$temporary/manifest.json"
(
    cd "$temporary/chunks"
    sha256sum -- * >../SHA256SUMS
)
chmod 0600 "$temporary/SHA256SUMS"
rm -- "$chunks_jsonl" "$archive"

for binding in "${inputs[@]}"; do
    path=${binding%:*}
    digest=${binding##*:}
    [[ "$(sha256sum "$path" | cut -d' ' -f1)" == "$digest" ]] \
        || { printf '{"code":"input_changed_during_package","state":"error"}\n'; exit 2; }
done
mv -- "$temporary" "$output"
published=1
printf '{"archive_bytes":%s,"archive_sha256":"%s","chunks":%s,"state":"packaged"}\n' \
    "$archive_bytes" "$archive_sha256" "$(find "$output/chunks" -maxdepth 1 -type f | wc -l)"
