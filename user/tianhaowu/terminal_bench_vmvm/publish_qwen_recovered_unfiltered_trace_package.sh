#!/usr/bin/env bash
set -euo pipefail
umask 077
export LC_ALL=C

fail() {
    printf '{"code":"%s","state":"error"}\n' "$1" >&2
    exit 2
}

required=(
    QWEN_PUBLISH_REPOSITORY QWEN_PUBLISH_SOURCE QWEN_PUBLISH_TARGET_RELATIVE
    QWEN_PUBLISH_WATCHER_STATE QWEN_PUBLISH_PACKAGE_JOBID_FILE
    QWEN_PUBLISH_TRANSACTION_DIR QWEN_PUBLISH_EXPECTED_REMOTE_HEAD
    QWEN_PUBLISH_EXPECTED_REMOTE_URL QWEN_PUBLISH_EXPECTED_PROJECT_REVISION
    QWEN_PUBLISH_EXPECTED_PACKAGER_SHA256 QWEN_PUBLISH_EXPECTED_WORKER_SHA256
    QWEN_PUBLISH_EXPECTED_ARCHIVE_VERIFIER_SHA256
    QWEN_PUBLISH_EXPECTED_SUBMIT_LINE_SHA256
    QWEN_PUBLISH_EXPECTED_SOURCE_JOB QWEN_PUBLISH_EXPECTED_POSTRUN_JOB
    QWEN_PUBLISH_EXPECTED_POSTRUN_WORKER_SHA256
    QWEN_PUBLISH_EXPECTED_POSTPROCESSOR_REVISION
    QWEN_PUBLISH_EXPECTED_PREDECESSOR_REVISION
    QWEN_PUBLISH_EXPECTED_SELECTION_CONTRACT_SHA256
    QWEN_PUBLISH_EXPECTED_PREVIOUS_MANIFEST_SHA256
    QWEN_PUBLISH_EXPECTED_CANONICAL_TASK_FILE_SHA256
    QWEN_PUBLISH_EXPECTED_RESULTS_SHA256
    QWEN_PUBLISH_EXPECTED_RETRY_CERTIFICATE_SHA256
    QWEN_PUBLISH_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256
    QWEN_PUBLISH_EXPECTED_RECOVERED_CERTIFICATE_SHA256
    QWEN_PUBLISH_EXPECTED_MERGE_MANIFEST_SHA256
    QWEN_PUBLISH_EXPECTED_POSTRUN_RECEIPT_SHA256
    QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256 QWEN_PUBLISH_EXPECTED_README_SHA256
    QWEN_PUBLISH_COMMIT_MESSAGE
)
for variable in "${required[@]}"; do
    value=${!variable:-}
    [[ -n $value && $value != *$'\n'* && $value != *$'\r'* ]] \
        || fail required_environment_invalid
done

[[ $# -eq 1 && $1 =~ ^[1-9][0-9]*$ ]] || fail package_job_id_required
package_job=$1
remote=${QWEN_PUBLISH_REMOTE:-origin}
branch=${QWEN_PUBLISH_BRANCH:-vmvm-sandbox}
expected_job_name=${QWEN_PUBLISH_EXPECTED_JOB_NAME:-qwen-recovered-package}
expected_archive_root=${QWEN_PUBLISH_EXPECTED_ARCHIVE_ROOT:-qwen-2499-recovered-unfiltered-108b713af-v6}
expected_archive_name=${QWEN_PUBLISH_EXPECTED_ARCHIVE_NAME:-${expected_archive_root}.tar.zst}
expected_chunk_bytes=${QWEN_PUBLISH_EXPECTED_CHUNK_BYTES:-95000000}
expected_compression=${QWEN_PUBLISH_EXPECTED_COMPRESSION:-zstd-19-long31}

[[ $remote == origin && $branch == vmvm-sandbox \
    && $expected_job_name == qwen-recovered-package \
    && $expected_archive_root =~ ^[A-Za-z0-9._-]+$ \
    && $expected_archive_name == "$expected_archive_root.tar.zst" \
    && $expected_chunk_bytes =~ ^[1-9][0-9]*$ \
    && $expected_chunk_bytes -lt 100000000 \
    && $expected_compression == zstd-19-long31 \
    && $QWEN_PUBLISH_EXPECTED_REMOTE_HEAD =~ ^[0-9a-f]{40}$ \
    && $QWEN_PUBLISH_EXPECTED_PROJECT_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_PUBLISH_EXPECTED_POSTPROCESSOR_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_PUBLISH_EXPECTED_PREDECESSOR_REVISION =~ ^[0-9a-f]{40}$ \
    && $QWEN_PUBLISH_EXPECTED_SOURCE_JOB =~ ^[1-9][0-9]*$ \
    && $QWEN_PUBLISH_EXPECTED_POSTRUN_JOB =~ ^[1-9][0-9]*$ \
    && $QWEN_PUBLISH_EXPECTED_REMOTE_URL != -* \
    && $QWEN_PUBLISH_COMMIT_MESSAGE != -* ]] \
    || fail publication_identity_invalid
if [[ $QWEN_PUBLISH_EXPECTED_REMOTE_URL == /* ]]; then
    canonical_remote_path=$(realpath -e -- "$QWEN_PUBLISH_EXPECTED_REMOTE_URL") \
        || fail publication_identity_invalid
    [[ $canonical_remote_path == "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" \
        && -d $canonical_remote_path && ! -L $canonical_remote_path ]] \
        || fail publication_identity_invalid
else
    [[ $QWEN_PUBLISH_EXPECTED_REMOTE_URL == https://github.com/thwu1/prime-rl.git ]] \
        || fail publication_identity_invalid
fi
for variable in \
    QWEN_PUBLISH_EXPECTED_PACKAGER_SHA256 \
    QWEN_PUBLISH_EXPECTED_WORKER_SHA256 \
    QWEN_PUBLISH_EXPECTED_ARCHIVE_VERIFIER_SHA256 \
    QWEN_PUBLISH_EXPECTED_SUBMIT_LINE_SHA256 \
    QWEN_PUBLISH_EXPECTED_POSTRUN_WORKER_SHA256 \
    QWEN_PUBLISH_EXPECTED_SELECTION_CONTRACT_SHA256 \
    QWEN_PUBLISH_EXPECTED_PREVIOUS_MANIFEST_SHA256 \
    QWEN_PUBLISH_EXPECTED_CANONICAL_TASK_FILE_SHA256 \
    QWEN_PUBLISH_EXPECTED_RESULTS_SHA256 \
    QWEN_PUBLISH_EXPECTED_RETRY_CERTIFICATE_SHA256 \
    QWEN_PUBLISH_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256 \
    QWEN_PUBLISH_EXPECTED_RECOVERED_CERTIFICATE_SHA256 \
    QWEN_PUBLISH_EXPECTED_MERGE_MANIFEST_SHA256 \
    QWEN_PUBLISH_EXPECTED_POSTRUN_RECEIPT_SHA256 \
    QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256 \
    QWEN_PUBLISH_EXPECTED_README_SHA256; do
    [[ ${!variable} =~ ^[0-9a-f]{64}$ ]] || fail publication_digest_invalid
done

repository=$(realpath -e -- "$QWEN_PUBLISH_REPOSITORY")
source=$(realpath -e -- "$QWEN_PUBLISH_SOURCE")
watcher_state=$(realpath -e -- "$QWEN_PUBLISH_WATCHER_STATE")
jobid_file=$(realpath -e -- "$QWEN_PUBLISH_PACKAGE_JOBID_FILE")
publisher=$(realpath -e -- "${BASH_SOURCE[0]}")
publisher_parent=$(dirname -- "$publisher") || fail publication_path_invalid
archive_verifier="$publisher_parent/verify_qwen_recovered_trace_archive.py"
repository_top=$(git -C "$repository" rev-parse --show-toplevel) \
    || fail publication_path_invalid
archive_verifier_sha256=$(sha256sum "$archive_verifier" | cut -d' ' -f1) \
    || fail publication_path_invalid
current_uid=$(id -u) || fail publication_path_invalid
[[ $repository == "$QWEN_PUBLISH_REPOSITORY" \
    && $source == "$QWEN_PUBLISH_SOURCE" \
    && $watcher_state == "$QWEN_PUBLISH_WATCHER_STATE" \
    && $jobid_file == "$QWEN_PUBLISH_PACKAGE_JOBID_FILE" \
    && -d $repository && ! -L $repository \
    && -d $source && ! -L $source \
    && $repository_top == "$repository" \
    && -f $archive_verifier && ! -L $archive_verifier \
    && $archive_verifier_sha256 == "$QWEN_PUBLISH_EXPECTED_ARCHIVE_VERIFIER_SHA256" ]] \
    || fail publication_path_invalid
[[ $QWEN_PUBLISH_TARGET_RELATIVE \
        =~ ^user/tianhaowu/terminal_bench_vmvm/trace_packages/[A-Za-z0-9._-]+$ ]] \
    || fail target_path_invalid
target_relative=$QWEN_PUBLISH_TARGET_RELATIVE
target="$repository/$target_relative"
target_dirname=$(dirname -- "$target") || fail target_path_invalid
target_parent=$(realpath -e -- "$target_dirname") || fail target_path_invalid
target_basename=$(basename -- "$target") || fail target_path_invalid
source_basename=$(basename -- "$source") || fail target_path_invalid
[[ $target == "$target_parent/$target_basename" \
    && $target_basename == "$expected_archive_root" \
    && $source_basename == "$expected_archive_root" ]] \
    || fail target_path_invalid
transaction_dirname=$(dirname -- "$QWEN_PUBLISH_TRANSACTION_DIR") \
    || fail transaction_path_invalid
transaction_basename=$(basename -- "$QWEN_PUBLISH_TRANSACTION_DIR") \
    || fail transaction_path_invalid
transaction_parent=$(realpath -e -- "$transaction_dirname") \
    || fail transaction_path_invalid
transaction_dir="$transaction_parent/$transaction_basename"
[[ $transaction_dir == "$QWEN_PUBLISH_TRANSACTION_DIR" \
    && $transaction_dir != / \
    && $transaction_basename =~ ^[A-Za-z0-9._-]+$ \
    && $transaction_dir != "$repository"/* \
    && ! -L $transaction_dir ]] \
    || fail transaction_path_invalid

owned_private_file() {
    local path=$1
    local metadata
    metadata=$(stat -c '%a:%h:%u' "$path") || return 1
    [[ -f $path && ! -L $path \
        && $metadata == "600:1:$current_uid" ]]
}

owned_private_snapshot() {
    local path=$1
    local metadata
    metadata=$(stat -c '%a:%h:%u' "$path") || return 1
    [[ -f $path && ! -L $path \
        && $metadata == "400:1:$current_uid" ]]
}

remote_config_valid() {
    local fetch_output push_output url_config_output url_config_status=0
    local -a fetch_urls push_urls
    url_config_output=$(git -C "$repository" config --show-origin --get-regexp '^url\.' 2>/dev/null) \
        || url_config_status=$?
    [[ $url_config_status -eq 1 && -z $url_config_output ]] || return 1
    fetch_output=$(git -C "$repository" remote get-url --all "$remote") || return 1
    push_output=$(git -C "$repository" remote get-url --push --all "$remote") || return 1
    [[ -n $fetch_output && -n $push_output ]] || return 1
    mapfile -t fetch_urls <<<"$fetch_output"
    mapfile -t push_urls <<<"$push_output"
    [[ ${#fetch_urls[@]} -eq 1 && ${fetch_urls[0]} == "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" \
        && ${#push_urls[@]} -eq 1 && ${push_urls[0]} == "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" ]]
}

read_remote_head() {
    local output record observed_head observed_ref extra
    local -a records
    output=$(
        git -C "$repository" ls-remote --exit-code \
            "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" "refs/heads/$branch"
    ) || return 1
    [[ -n $output ]] || return 1
    mapfile -t records <<<"$output"
    [[ ${#records[@]} -eq 1 ]] || return 1
    record=${records[0]}
    IFS=$'\t' read -r observed_head observed_ref extra <<<"$record"
    [[ -z ${extra:-} && $observed_head =~ ^[0-9a-f]{40}$ \
        && $observed_ref == "refs/heads/$branch" ]] || return 1
    printf '%s\n' "$observed_head"
}

repository_clean() {
    local output
    output=$(git -C "$repository" status --porcelain=v1 --untracked-files=all) || return 1
    [[ -z $output ]]
}

validate_package() {
    local root=$1
    local manifest="$root/manifest.json"
    local chunks="$root/chunks"
    local expected_top observed_top manifest_names observed_names unexpected_entries
    local name bytes digest path archive_bytes archive_sha256
    local reassembled_bytes reassembled_sha256 root_metadata chunks_metadata file_metadata
    local manifest_digest readme_digest chunk_size chunk_digest
    local -a chunk_paths=()
    root_metadata=$(stat -c '%a:%u' "$root") || return 1
    chunks_metadata=$(stat -c '%a:%u' "$chunks") || return 1
    [[ -d $root && ! -L $root && $root_metadata == "700:$current_uid" \
        && -d $chunks && ! -L $chunks && $chunks_metadata == "700:$current_uid" ]] \
        || return 1
    expected_top='README.md SHA256SUMS chunks manifest.json'
    observed_top=$(find "$root" -mindepth 1 -maxdepth 1 -printf '%f\n' \
        | sort | paste -sd' ' -) || return 1
    [[ $observed_top == "$expected_top" ]] || return 1
    for path in "$manifest" "$root/SHA256SUMS" "$root/README.md"; do
        file_metadata=$(stat -c '%a:%h:%u' "$path") || return 1
        [[ -f $path && ! -L $path && $file_metadata == "600:1:$current_uid" ]] \
            || return 1
    done
    unexpected_entries=$(find "$chunks" -mindepth 1 -maxdepth 1 ! -type f -print -quit) \
        || return 1
    manifest_digest=$(sha256sum "$manifest" | cut -d' ' -f1) || return 1
    readme_digest=$(sha256sum "$root/README.md" | cut -d' ' -f1) || return 1
    [[ $manifest_digest == "$QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256" \
        && $readme_digest == "$QWEN_PUBLISH_EXPECTED_README_SHA256" \
        && -z $unexpected_entries ]] \
        || return 1
    jq -e \
        --arg project_revision "$QWEN_PUBLISH_EXPECTED_PROJECT_REVISION" \
        --arg packager_sha256 "$QWEN_PUBLISH_EXPECTED_PACKAGER_SHA256" \
        --arg worker_sha256 "$QWEN_PUBLISH_EXPECTED_WORKER_SHA256" \
        --argjson source_job "$QWEN_PUBLISH_EXPECTED_SOURCE_JOB" \
        --argjson postrun_job "$QWEN_PUBLISH_EXPECTED_POSTRUN_JOB" \
        --arg postrun_worker_sha256 "$QWEN_PUBLISH_EXPECTED_POSTRUN_WORKER_SHA256" \
        --arg postprocessor_revision "$QWEN_PUBLISH_EXPECTED_POSTPROCESSOR_REVISION" \
        --arg predecessor_revision "$QWEN_PUBLISH_EXPECTED_PREDECESSOR_REVISION" \
        --arg selection_sha256 "$QWEN_PUBLISH_EXPECTED_SELECTION_CONTRACT_SHA256" \
        --arg previous_sha256 "$QWEN_PUBLISH_EXPECTED_PREVIOUS_MANIFEST_SHA256" \
        --arg canonical_sha256 "$QWEN_PUBLISH_EXPECTED_CANONICAL_TASK_FILE_SHA256" \
        --arg results_sha256 "$QWEN_PUBLISH_EXPECTED_RESULTS_SHA256" \
        --arg retry_sha256 "$QWEN_PUBLISH_EXPECTED_RETRY_CERTIFICATE_SHA256" \
        --arg superseding_sha256 "$QWEN_PUBLISH_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256" \
        --arg recovered_sha256 "$QWEN_PUBLISH_EXPECTED_RECOVERED_CERTIFICATE_SHA256" \
        --arg merge_sha256 "$QWEN_PUBLISH_EXPECTED_MERGE_MANIFEST_SHA256" \
        --arg postrun_receipt_sha256 "$QWEN_PUBLISH_EXPECTED_POSTRUN_RECEIPT_SHA256" \
        --arg archive_root "$expected_archive_root" \
        --arg archive_name "$expected_archive_name" \
        --arg compression "$expected_compression" \
        --argjson chunk_bytes "$expected_chunk_bytes" '
        type == "object"
        and (keys | sort) == ["archive", "chunk_bytes", "chunks", "coverage", "inputs", "kind", "lineage", "package_version", "package_worker", "packager", "project_revision", "schema_version", "state"]
        and .schema_version == 1
        and .kind == "qwen-2499-recovered-unfiltered-trajectory-package"
        and .state == "ready" and .package_version == "v6"
        and .project_revision == $project_revision
        and (.packager | keys | sort) == ["bytes", "sha256"]
        and (.packager.bytes | type) == "number" and .packager.bytes > 0
        and (.packager.bytes | floor) == .packager.bytes
        and .packager.sha256 == $packager_sha256
        and (.package_worker | keys | sort) == ["bytes", "sha256"]
        and (.package_worker.bytes | type) == "number" and .package_worker.bytes > 0
        and (.package_worker.bytes | floor) == .package_worker.bytes
        and .package_worker.sha256 == $worker_sha256
        and (.coverage | keys | sort) == ["canonical_tasks", "outcomes"]
        and .coverage.canonical_tasks == 2499
        and (.coverage.outcomes | keys | sort) == ["error", "positive", "zero"]
        and ([.coverage.outcomes.error, .coverage.outcomes.positive, .coverage.outcomes.zero]
            | all(.[]; type == "number" and . >= 0 and floor == .))
        and ((.coverage.outcomes.error + .coverage.outcomes.positive + .coverage.outcomes.zero) == 2499)
        and (.lineage | keys | sort) == ["canonical_task_file_sha256", "postprocessor_revision", "postrun_job_id", "postrun_receipt_sha256", "postrun_worker_sha256", "predecessor_revision", "previous_package_manifest_sha256", "recovered_certificate_sha256", "recovered_merge_manifest_sha256", "retry_certificate_sha256", "selection_contract_sha256", "source_job", "superseding_certificate_sha256"]
        and .lineage.source_job == $source_job
        and .lineage.postrun_job_id == $postrun_job
        and .lineage.postrun_worker_sha256 == $postrun_worker_sha256
        and .lineage.postprocessor_revision == $postprocessor_revision
        and .lineage.predecessor_revision == $predecessor_revision
        and .lineage.selection_contract_sha256 == $selection_sha256
        and .lineage.previous_package_manifest_sha256 == $previous_sha256
        and .lineage.canonical_task_file_sha256 == $canonical_sha256
        and .lineage.retry_certificate_sha256 == $retry_sha256
        and .lineage.superseding_certificate_sha256 == $superseding_sha256
        and .lineage.recovered_certificate_sha256 == $recovered_sha256
        and .lineage.recovered_merge_manifest_sha256 == $merge_sha256
        and .lineage.postrun_receipt_sha256 == $postrun_receipt_sha256
        and (.inputs | keys | sort) == ["postrun_receipt", "postrun_worker", "previous_package_manifest", "recovered_certificate", "recovered_merge_manifest", "results", "retry_certificate", "superseding_certificate"]
        and (.inputs.results | keys | sort) == ["bytes", "rows", "sha256"]
        and all([.inputs.recovered_certificate, .inputs.recovered_merge_manifest,
            .inputs.retry_certificate, .inputs.superseding_certificate,
            .inputs.postrun_receipt, .inputs.postrun_worker,
            .inputs.previous_package_manifest][]; (keys | sort) == ["bytes", "sha256"])
        and all([.inputs.results, .inputs.recovered_certificate,
            .inputs.recovered_merge_manifest, .inputs.retry_certificate,
            .inputs.superseding_certificate, .inputs.postrun_receipt,
            .inputs.postrun_worker, .inputs.previous_package_manifest][];
            (.bytes | type) == "number" and .bytes > 0 and (.bytes | floor) == .bytes
            and (.sha256 | type) == "string" and (.sha256 | test("^[0-9a-f]{64}$")))
        and .inputs.results.rows == 2499
        and .inputs.results.sha256 == $results_sha256
        and .inputs.retry_certificate.sha256 == $retry_sha256
        and .inputs.superseding_certificate.sha256 == $superseding_sha256
        and .inputs.recovered_certificate.sha256 == $recovered_sha256
        and .inputs.recovered_merge_manifest.sha256 == $merge_sha256
        and .inputs.postrun_receipt.sha256 == $postrun_receipt_sha256
        and .inputs.postrun_worker.sha256 == $postrun_worker_sha256
        and .inputs.previous_package_manifest.sha256 == $previous_sha256
        and (.archive | keys | sort) == ["bytes", "compression", "member_count", "members", "name", "sha256"]
        and .archive.name == $archive_name and .archive.compression == $compression
        and .archive.member_count == 7
        and (.archive.bytes | type) == "number" and .archive.bytes > 0
        and (.archive.bytes | floor) == .archive.bytes
        and (.archive.sha256 | type) == "string"
        and (.archive.sha256 | test("^[0-9a-f]{64}$"))
        and (.archive.members | map(.name)) == [
            ($archive_root + "/merge_manifest.json"),
            ($archive_root + "/postrun_receipt-src108b713af-v6.json"),
            ($archive_root + "/postrun_worker.sbatch"),
            ($archive_root + "/qwen_2499_error_retry_run_certificate.json"),
            ($archive_root + "/qwen_2499_error_retry_superseding_certificate.json"),
            ($archive_root + "/qwen_2499_recovered_results_certificate.json"),
            ($archive_root + "/results.jsonl")]
        and all(.archive.members[]; (keys | sort) == ["bytes", "name", "sha256"]
            and (.bytes | type) == "number" and .bytes > 0 and (.bytes | floor) == .bytes
            and (.sha256 | type) == "string" and (.sha256 | test("^[0-9a-f]{64}$")))
        and .archive.members[0] == (.inputs.recovered_merge_manifest + {name:($archive_root + "/merge_manifest.json")})
        and .archive.members[1] == (.inputs.postrun_receipt + {name:($archive_root + "/postrun_receipt-src108b713af-v6.json")})
        and .archive.members[2] == (.inputs.postrun_worker + {name:($archive_root + "/postrun_worker.sbatch")})
        and .archive.members[3] == (.inputs.retry_certificate + {name:($archive_root + "/qwen_2499_error_retry_run_certificate.json")})
        and .archive.members[4] == (.inputs.superseding_certificate + {name:($archive_root + "/qwen_2499_error_retry_superseding_certificate.json")})
        and .archive.members[5] == (.inputs.recovered_certificate + {name:($archive_root + "/qwen_2499_recovered_results_certificate.json")})
        and .archive.members[6] == ({bytes:.inputs.results.bytes,sha256:.inputs.results.sha256,name:($archive_root + "/results.jsonl")})
        and .chunk_bytes == $chunk_bytes
        and (.chunks | type) == "array" and (.chunks | length) > 0
        and all(.chunks[]; (keys | sort) == ["bytes", "name", "sha256"]
            and (.name | type) == "string"
            and (.name | startswith($archive_name + "."))
            and (.name | test("\\.[0-9]{3}\\.part$"))
            and (.bytes | type) == "number" and .bytes > 0 and .bytes <= $chunk_bytes
            and (.bytes | floor) == .bytes
            and (.sha256 | type) == "string" and (.sha256 | test("^[0-9a-f]{64}$")))
        and ((.chunks | map(.name) | unique | length) == (.chunks | length))
    ' "$manifest" >/dev/null 2>&1 || return 1

    manifest_names=$(jq -r '.chunks[].name' "$manifest") || return 1
    observed_names=$(find "$chunks" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' \
        | sort) || return 1
    [[ $manifest_names == "$observed_names" ]] || return 1
    chunk_count=$(jq -r '.chunks | length' "$manifest") || return 1
    [[ $chunk_count =~ ^[1-9][0-9]*$ && $chunk_count -le 1000 ]] || return 1
    chunk_records=$(jq -r '.chunks[] | [.name, (.bytes | tostring), .sha256] | @tsv' \
        "$manifest") || return 1
    [[ -n $chunk_records ]] || return 1
    chunk_index=0
    while IFS=$'\t' read -r name bytes digest; do
        printf -v expected_chunk_name '%s.%03d.part' "$expected_archive_name" "$chunk_index"
        [[ $name =~ ^[A-Za-z0-9._-]+$ && $name =~ \.[0-9]{3}\.part$ \
            && $name == "$expected_chunk_name" \
            && $bytes =~ ^[1-9][0-9]*$ && $bytes -lt 100000000 \
            && $digest =~ ^[0-9a-f]{64}$ ]] || return 1
        if ((chunk_index + 1 < chunk_count)); then
            [[ $bytes == "$expected_chunk_bytes" ]] || return 1
        else
            ((bytes <= expected_chunk_bytes)) || return 1
        fi
        path="$chunks/$name"
        file_metadata=$(stat -c '%a:%h:%u' "$path") || return 1
        chunk_size=$(stat -c %s "$path") || return 1
        chunk_digest=$(sha256sum "$path" | cut -d' ' -f1) || return 1
        [[ -f $path && ! -L $path && $file_metadata == "600:1:$current_uid" \
            && $chunk_size == "$bytes" && $chunk_digest == "$digest" ]] || return 1
        chunk_paths+=("$path")
        chunk_index=$((chunk_index + 1))
    done <<<"$chunk_records"
    [[ ${#chunk_paths[@]} -eq $chunk_count && $chunk_index -eq $chunk_count ]] || return 1
    (cd "$chunks" && sha256sum --strict -c ../SHA256SUMS >/dev/null) || return 1
    (cd "$chunks" && sha256sum -- *) | cmp -s - "$root/SHA256SUMS" || return 1
    archive_bytes=$(jq -r '.archive.bytes' "$manifest") || return 1
    archive_sha256=$(jq -r '.archive.sha256' "$manifest") || return 1
    reassembled_bytes=$(cat "${chunk_paths[@]}" | wc -c) || return 1
    reassembled_sha256=$(cat "${chunk_paths[@]}" | sha256sum | cut -d' ' -f1) || return 1
    [[ $reassembled_bytes == "$archive_bytes" \
        && $reassembled_sha256 == "$archive_sha256" ]] || return 1
    cat "${chunk_paths[@]}" | zstd -q --long=31 -t || return 1
    cat "${chunk_paths[@]}" | zstd -q --long=31 -dc \
        | python3 "$archive_verifier" "$manifest" || return 1
}

expected_paths=
expected_manifest_sha256=
expected_readme_sha256=
expected_sums_sha256=
manifest_snapshot=
readme_snapshot=
sums_snapshot=
snapshot_temporary=
transaction_repo=
transaction_index=
empty_hooks=
transaction_receipt=
current_phase=startup
current_commit=
receipt_ready=0
lock_owned=0

snapshot_private_file() {
    local source_path=$1 destination=$2 expected_digest=$3 observed_digest stale metadata
    for stale in "$transaction_dir"/.snapshot.*; do
        [[ -e $stale || -L $stale ]] || continue
        metadata=$(stat -c '%a:%h:%u' "$stale") || return 1
        [[ -f $stale && ! -L $stale && $metadata == "600:1:$current_uid" ]] \
            || return 1
        rm -f -- "$stale" || return 1
    done
    if [[ ! -e $destination && ! -L $destination ]]; then
        snapshot_temporary=$(mktemp "$transaction_dir/.snapshot.XXXXXXXX") || return 1
        cp -- "$source_path" "$snapshot_temporary" || return 1
        chmod 0400 "$snapshot_temporary" || return 1
        observed_digest=$(sha256sum "$snapshot_temporary" | cut -d' ' -f1) || return 1
        [[ $observed_digest == "$expected_digest" ]] || return 1
        mv -T -n -- "$snapshot_temporary" "$destination" || return 1
        [[ ! -e $snapshot_temporary ]] || return 1
        snapshot_temporary=
    fi
    owned_private_snapshot "$destination" || return 1
    observed_digest=$(sha256sum "$destination" | cut -d' ' -f1) || return 1
    [[ $observed_digest == "$expected_digest" ]]
}

ensure_sums_snapshot() {
    local generated metadata
    generated=$(mktemp "$transaction_dir/.snapshot.XXXXXXXX") || return 1
    snapshot_temporary=$generated
    jq -r '.chunks[] | "\(.sha256)  \(.name)"' "$manifest_snapshot" >"$generated" \
        || return 1
    chmod 0400 "$generated" || return 1
    if [[ ! -e $sums_snapshot && ! -L $sums_snapshot ]]; then
        mv -T -n -- "$generated" "$sums_snapshot" || return 1
        [[ ! -e $generated ]] || return 1
    else
        cmp -s -- "$generated" "$sums_snapshot" || return 1
        rm -f -- "$generated" || return 1
    fi
    snapshot_temporary=
    metadata=$(stat -c '%a:%h:%u' "$sums_snapshot") || return 1
    [[ -f $sums_snapshot && ! -L $sums_snapshot \
        && $metadata == "400:1:$current_uid" ]]
}

write_receipt() {
    local state=$1 phase=$2 commit=${3:-} temporary timestamp
    temporary=$(mktemp "$transaction_dir/.receipt.XXXXXXXX") || return 1
    chmod 0600 "$temporary" || return 1
    timestamp=$(date -u +'%Y-%m-%dT%H:%M:%SZ') || return 1
    jq -cn --arg state "$state" --arg phase "$phase" --arg commit "$commit" \
        --argjson package_job "$package_job" \
        --arg remote_head "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" \
        --arg remote_url "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" \
        --arg target_relative "$target_relative" \
        --arg manifest_sha256 "$QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256" \
        --arg timestamp "$timestamp" \
        '{schema_version:1,kind:"qwen-recovered-package-publication",state:$state,
          phase:$phase,package_job:$package_job,expected_remote_head:$remote_head,
          expected_remote_url:$remote_url,target_relative:$target_relative,
          manifest_sha256:$manifest_sha256,
          commit:(if $commit == "" then null else $commit end),timestamp_utc:$timestamp}' \
        >"$temporary" || return 1
    mv -T -- "$temporary" "$transaction_receipt" || return 1
    chmod 0600 "$transaction_receipt" || return 1
}

validate_receipt() {
    owned_private_file "$transaction_receipt" || return 1
    jq -e --argjson package_job "$package_job" \
        --arg remote_head "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" \
        --arg remote_url "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" \
        --arg target_relative "$target_relative" \
        --arg manifest_sha256 "$QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256" '
        type == "object"
        and (keys | sort) == ["commit", "expected_remote_head", "expected_remote_url", "kind", "manifest_sha256", "package_job", "phase", "schema_version", "state", "target_relative", "timestamp_utc"]
        and .schema_version == 1
        and .kind == "qwen-recovered-package-publication"
        and (.state | IN("initialized", "committed", "pushing", "interrupted", "published", "failed"))
        and (.phase | type) == "string"
        and .package_job == $package_job
        and .expected_remote_head == $remote_head
        and .expected_remote_url == $remote_url
        and .target_relative == $target_relative
        and .manifest_sha256 == $manifest_sha256
        and (.commit == null or ((.commit | type) == "string" and (.commit | test("^[0-9a-f]{40}$"))))
        and (.timestamp_utc | type) == "string"
    ' "$transaction_receipt" >/dev/null
}

txn_git() {
    GIT_INDEX_FILE="$transaction_index" \
        git -c core.hooksPath="$empty_hooks" -c push.followTags=false \
            --git-dir="$transaction_repo" "$@"
}

expected_file_digest() {
    local relative_path=$1 chunk_name
    case "$relative_path" in
        "$target_relative/manifest.json") printf '%s\n' "$expected_manifest_sha256" ;;
        "$target_relative/README.md") printf '%s\n' "$expected_readme_sha256" ;;
        "$target_relative/SHA256SUMS") printf '%s\n' "$expected_sums_sha256" ;;
        "$target_relative/chunks/"*)
            chunk_name=${relative_path##*/}
            jq -r --arg name "$chunk_name" \
                '.chunks[] | select(.name == $name) | .sha256' "$manifest_snapshot"
            ;;
        *) return 1 ;;
    esac
}

validate_tree_blobs() {
    local tree=$1 observed_paths relative_path record mode type oid bytes digest
    local expected_digest chunk_name manifest_bytes
    observed_paths=$(txn_git ls-tree -r --name-only "$tree" -- "$target_relative" | sort) \
        || return 1
    [[ $observed_paths == "$expected_paths" ]] || return 1
    while IFS= read -r relative_path; do
        [[ -n $relative_path ]] || return 1
        record=$(txn_git ls-tree "$tree" -- "$relative_path" | cut -f1) || return 1
        IFS=' ' read -r mode type oid <<<"$record"
        [[ $mode == 100644 && $type == blob && $oid =~ ^[0-9a-f]{40,64}$ ]] || return 1
        bytes=$(txn_git cat-file -s "$oid") || return 1
        digest=$(txn_git cat-file blob "$oid" | sha256sum | cut -d' ' -f1) || return 1
        expected_digest=$(expected_file_digest "$relative_path") || return 1
        [[ $digest == "$expected_digest" ]] || return 1
        if [[ $relative_path == "$target_relative/chunks/"* ]]; then
            chunk_name=${relative_path##*/}
            manifest_bytes=$(jq -r --arg name "$chunk_name" \
                '.chunks[] | select(.name == $name) | .bytes' "$manifest_snapshot") || return 1
            [[ $bytes == "$manifest_bytes" && $bytes -lt 100000000 ]] || return 1
        fi
    done <<<"$expected_paths"
}

validate_transaction_commit() {
    local commit=$1 record parent changed_paths transaction_metadata transaction_head
    local -a fields
    transaction_metadata=$(stat -c '%a:%u' "$transaction_repo") || return 1
    [[ -d $transaction_repo && ! -L $transaction_repo \
        && $transaction_metadata == "700:$current_uid" \
        && $commit =~ ^[0-9a-f]{40}$ ]] || return 1
    txn_git cat-file -e "$commit^{commit}" || return 1
    record=$(txn_git rev-list --parents -n 1 "$commit") || return 1
    read -r -a fields <<<"$record"
    [[ ${#fields[@]} -eq 2 && ${fields[0]} == "$commit" ]] || return 1
    parent=${fields[1]}
    transaction_head=$(txn_git rev-parse HEAD) || return 1
    [[ $parent == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" \
        && $transaction_head == "$commit" ]] || return 1
    changed_paths=$(txn_git diff-tree --no-commit-id --name-only -r "$parent" "$commit" | sort) \
        || return 1
    [[ $changed_paths == "$expected_paths" ]] || return 1
    validate_tree_blobs "$commit"
}

repository_base_valid() {
    local head remote_head
    repository_clean || return 1
    remote_config_valid || return 1
    head=$(git -C "$repository" rev-parse HEAD) || return 1
    [[ $head == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]] || return 1
    remote_head=$(read_remote_head) || return 1
    [[ $remote_head == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]]
}

cleanup_snapshot_temporary() {
    if [[ -n $snapshot_temporary \
        && $snapshot_temporary == "$transaction_dir/.snapshot."* \
        && -f $snapshot_temporary && ! -L $snapshot_temporary ]]; then
        rm -f -- "$snapshot_temporary" || true
    fi
    snapshot_temporary=
}

on_signal() {
    local code=$1 remote_head=
    trap - EXIT INT TERM
    if [[ $receipt_ready == 1 ]]; then
        if [[ $current_commit =~ ^[0-9a-f]{40}$ ]] \
            && validate_transaction_commit "$current_commit"; then
            remote_head=$(read_remote_head 2>/dev/null || true)
            if [[ $remote_head == "$current_commit" ]]; then
                write_receipt published reconciled "$current_commit" || true
            else
                write_receipt interrupted "$current_phase" "$current_commit" || true
            fi
        else
            write_receipt interrupted "$current_phase" "" || true
        fi
    fi
    if [[ $lock_owned == 1 ]]; then
        flock -u 9 || true
    fi
    cleanup_snapshot_temporary
    exit "$code"
}

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ $lock_owned == 1 ]]; then
        flock -u 9 || true
    fi
    cleanup_snapshot_temporary
    exit "$status"
}

owned_private_file "$watcher_state" || fail watcher_state_invalid
owned_private_file "$jobid_file" || fail package_job_receipt_invalid
if ! jq -e --argjson expected_job "$package_job" '
    type == "object"
    and (keys | sort) == ["job_id", "kind", "schema_version", "stage", "state", "timestamp_utc"]
    and .schema_version == 1
    and .kind == "qwen-recovery-chain-watch"
    and .stage == "chain" and .state == "completed"
    and .job_id == $expected_job and (.timestamp_utc | type) == "string"
' "$watcher_state" >/dev/null; then
    fail watcher_chain_not_complete
fi
receipt_job=$(cat "$jobid_file")
[[ $receipt_job == "$package_job" ]] || fail package_job_receipt_invalid
cmp -s -- "$jobid_file" <(printf '%s\n' "$package_job") \
    || fail package_job_receipt_invalid
accounting_output=$(
    sacct -j "$package_job" -X -n -P \
        -o JobIDRaw,JobName,State,ExitCode,SubmitLine \
        | sed '/^[[:space:]]*$/d'
) || fail package_job_accounting_invalid
[[ -n $accounting_output ]] || fail package_job_accounting_invalid
mapfile -t accounting <<<"$accounting_output"
[[ ${#accounting[@]} -eq 1 ]] || fail package_job_accounting_invalid
IFS='|' read -r observed_job observed_name observed_state observed_exit \
    observed_submit_line accounting_extra <<<"${accounting[0]}"
[[ $observed_job == "$package_job" && $observed_state == COMPLETED \
    && $observed_exit == 0:0 && -z ${accounting_extra:-} ]] \
    || fail package_job_not_successful
[[ $observed_name == "$expected_job_name" ]] || fail package_job_provenance_invalid

controller_status=0
controller_output=$(scontrol show job -o "$package_job" 2>&1) \
    || controller_status=$?
if [[ $controller_status -eq 0 ]]; then
    controller_job=$(sed -n 's/^JobId=\([^ ]*\).*/\1/p' <<<"$controller_output")
    controller_name=$(sed -n 's/.* JobName=\([^ ]*\).*/\1/p' <<<"$controller_output")
    [[ $controller_job == "$package_job" \
        && $controller_name == "$expected_job_name" ]] \
        || fail package_job_provenance_invalid
    observed_worker_sha256=$(
        scontrol write batch_script "$package_job" - 2>/dev/null \
            | sha256sum | cut -d' ' -f1
    ) || fail package_job_provenance_invalid
    [[ $observed_worker_sha256 == "$QWEN_PUBLISH_EXPECTED_WORKER_SHA256" ]] \
        || fail package_job_provenance_invalid
elif [[ $controller_status -eq 1 \
    && $controller_output == 'slurm_load_jobs error: Invalid job id specified' ]]; then
    observed_submit_line_sha256=$(
        printf '%s' "$observed_submit_line" | sha256sum | cut -d' ' -f1
    ) || fail package_job_provenance_invalid
    [[ $observed_submit_line_sha256 \
        == "$QWEN_PUBLISH_EXPECTED_SUBMIT_LINE_SHA256" ]] \
        || fail package_job_provenance_invalid
else
    fail package_job_provenance_invalid
fi

git_common_dir=$(git -C "$repository" rev-parse --git-common-dir)
if [[ $git_common_dir != /* ]]; then
    git_common_dir="$repository/$git_common_dir"
fi
git_common_dir=$(realpath -e -- "$git_common_dir")
lock_file="$git_common_dir/qwen-package-publish-vmvm-sandbox.lock"
exec 9>"$lock_file"
chmod 0600 "$lock_file"
flock -n 9 || fail publication_locked
lock_owned=1
trap cleanup EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

repository_clean || fail repository_not_clean
remote_config_valid || fail repository_remote_invalid
main_head=$(git -C "$repository" rev-parse HEAD) \
    || fail repository_not_at_expected_remote_head
[[ $main_head == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]] \
    || fail repository_not_at_expected_remote_head
validate_package "$source" || fail package_validation_failed
if [[ ! -e $transaction_dir ]]; then
    mkdir -m 700 -- "$transaction_dir" || fail transaction_create_failed
fi
[[ -d $transaction_dir && ! -L $transaction_dir \
    ]] || fail transaction_path_invalid
transaction_metadata=$(stat -c '%a:%u' "$transaction_dir") \
    || fail transaction_path_invalid
[[ $transaction_metadata == "700:$current_uid" ]] \
    || fail transaction_path_invalid
transaction_repo="$transaction_dir/repository.git"
transaction_index="$transaction_dir/index"
empty_hooks="$transaction_dir/hooks"
transaction_receipt="$transaction_dir/receipt.json"
manifest_snapshot="$transaction_dir/manifest.snapshot.json"
readme_snapshot="$transaction_dir/README.snapshot.md"
sums_snapshot="$transaction_dir/SHA256SUMS.snapshot"
if [[ ! -e $transaction_receipt ]]; then
    transaction_entries=$(find "$transaction_dir" -mindepth 1 -maxdepth 1 -print -quit) \
        || fail transaction_path_invalid
    [[ -z $transaction_entries ]] || fail transaction_uninitialized_not_empty
    write_receipt initialized startup "" || fail transaction_receipt_write_failed
fi
validate_receipt || fail transaction_receipt_invalid
receipt_ready=1
snapshot_private_file "$source/manifest.json" "$manifest_snapshot" \
    "$QWEN_PUBLISH_EXPECTED_MANIFEST_SHA256" || fail manifest_snapshot_invalid
snapshot_private_file "$source/README.md" "$readme_snapshot" \
    "$QWEN_PUBLISH_EXPECTED_README_SHA256" || fail readme_snapshot_invalid
ensure_sums_snapshot || fail sums_snapshot_invalid
expected_manifest_sha256=$(sha256sum "$manifest_snapshot" | cut -d' ' -f1) \
    || fail manifest_snapshot_invalid
expected_readme_sha256=$(sha256sum "$readme_snapshot" | cut -d' ' -f1) \
    || fail readme_snapshot_invalid
expected_sums_sha256=$(sha256sum "$sums_snapshot" | cut -d' ' -f1) \
    || fail sums_snapshot_invalid
expected_paths=$(
    {
        printf '%s\n' "$target_relative/README.md" "$target_relative/SHA256SUMS" \
            "$target_relative/manifest.json"
        jq -r --arg prefix "$target_relative/chunks/" \
            '.chunks[].name | $prefix + .' "$manifest_snapshot"
    } | sort
) || fail package_path_set_invalid
[[ -n $expected_paths ]] || fail package_path_set_invalid
while IFS= read -r relative_path; do
    [[ -n $relative_path ]] || fail package_path_set_invalid
    for attribute in filter diff merge text eol working-tree-encoding ident; do
        attribute_record=$(git -C "$repository" check-attr --cached "$attribute" -- "$relative_path") \
            || fail git_attribute_forbidden
        [[ $attribute_record == "$relative_path: $attribute: unspecified" ]] \
            || fail git_attribute_forbidden
    done
done <<<"$expected_paths"
mkdir -m 700 -- "$empty_hooks" 2>/dev/null || true
hook_entries=$(find "$empty_hooks" -mindepth 1 -maxdepth 1 -print -quit) \
    || fail transaction_hooks_invalid
hook_metadata=$(stat -c '%a:%u' "$empty_hooks") || fail transaction_hooks_invalid
[[ -d $empty_hooks && ! -L $empty_hooks \
    && $hook_metadata == "700:$current_uid" && -z $hook_entries ]] \
    || fail transaction_hooks_invalid

current_commit=$(jq -r '.commit // empty' "$transaction_receipt")
if [[ -n $current_commit ]]; then
    current_phase=reconcile
    validate_transaction_commit "$current_commit" || fail transaction_commit_invalid
    remote_head=$(read_remote_head 2>/dev/null || true)
    if [[ $remote_head == "$current_commit" ]]; then
        write_receipt published reconciled "$current_commit" \
            || fail transaction_receipt_write_failed
        trap - EXIT INT TERM
        flock -u 9
        lock_owned=0
        printf '{"commit":"%s","push_status":0,"state":"published","tasks":2499}\n' \
            "$current_commit"
        exit 0
    fi
    [[ $remote_head == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]] \
        || fail push_outcome_ambiguous
else
    current_phase=prepare
    repository_base_valid || fail repository_not_at_expected_remote_head
    base_target=$(git -C "$repository" ls-tree -r --name-only \
        "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" -- "$target_relative") \
        || fail transaction_base_invalid
    [[ ! -e $target && ! -L $target && -z $base_target ]] \
        || fail target_already_exists
    if [[ -e $transaction_repo ]]; then
        [[ -d $transaction_repo && ! -L $transaction_repo \
            && $transaction_repo == "$transaction_dir/repository.git" ]] \
            || fail transaction_repository_invalid
        rm -rf -- "$transaction_repo"
    fi
    if [[ -e $transaction_index || -L $transaction_index ]]; then
        [[ -f $transaction_index && ! -L $transaction_index \
            && $transaction_index == "$transaction_dir/index" ]] \
            || fail transaction_index_invalid
        rm -f -- "$transaction_index"
    fi
    git -c core.hooksPath="$empty_hooks" clone --bare --shared --no-tags \
        "$repository" "$transaction_repo" >/dev/null 2>&1 \
        || fail transaction_clone_failed
    chmod 0700 "$transaction_repo"
    txn_git cat-file -e "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD^{commit}" \
        || fail transaction_base_invalid
    txn_git read-tree "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"
    while IFS= read -r relative_path; do
        source_relative=${relative_path#"$target_relative/"}
        case "$source_relative" in
            manifest.json) source_path=$manifest_snapshot ;;
            README.md) source_path=$readme_snapshot ;;
            SHA256SUMS) source_path=$sums_snapshot ;;
            chunks/*) source_path="$source/$source_relative" ;;
            *) fail package_path_set_invalid ;;
        esac
        [[ -f $source_path && ! -L $source_path ]] || fail package_path_set_invalid
        oid=$(txn_git hash-object -w --no-filters "$source_path") \
            || fail transaction_blob_write_failed
        [[ $oid =~ ^[0-9a-f]{40,64}$ ]] || fail transaction_blob_write_failed
        txn_git update-index --add --cacheinfo "100644,$oid,$relative_path" \
            || fail transaction_index_write_failed
    done <<<"$expected_paths"
    indexed_paths=$(txn_git diff --cached --name-only "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" | sort)
    [[ $indexed_paths == "$expected_paths" ]] || fail transaction_index_path_set_invalid
    tree=$(txn_git write-tree) || fail transaction_tree_write_failed
    author_name=$(git -C "$repository" config user.name) || fail commit_identity_invalid
    author_email=$(git -C "$repository" config user.email) || fail commit_identity_invalid
    [[ -n $author_name && -n $author_email \
        && $author_name != *$'\n'* && $author_email != *$'\n'* ]] \
        || fail commit_identity_invalid
    generated_commit=$(
        printf '%s\n' "$QWEN_PUBLISH_COMMIT_MESSAGE" \
            | GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
                GIT_COMMITTER_NAME="$author_name" GIT_COMMITTER_EMAIL="$author_email" \
                txn_git commit-tree "$tree" -p "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD"
    ) || fail transaction_commit_failed
    [[ $generated_commit =~ ^[0-9a-f]{40}$ ]] || fail transaction_commit_failed
    txn_git update-ref --no-deref HEAD "$generated_commit" \
        || fail transaction_commit_failed
    current_commit=$generated_commit
    validate_transaction_commit "$current_commit" || fail transaction_commit_invalid
    write_receipt committed prepared "$current_commit" \
        || fail transaction_receipt_write_failed
fi

current_phase=push
repository_clean || fail repository_changed_before_push
remote_config_valid || fail repository_remote_invalid
main_head=$(git -C "$repository" rev-parse HEAD) \
    || fail repository_changed_before_push
[[ $main_head == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]] \
    || fail repository_changed_before_push
remote_before_push=$(read_remote_head) || fail push_precondition_ambiguous
[[ $remote_before_push == "$QWEN_PUBLISH_EXPECTED_REMOTE_HEAD" ]] \
    || fail remote_changed_before_push
# Revalidate the receipt-pinned commit at the last possible point before the
# network mutation.  The push below names that immutable object directly, so a
# concurrent change to the transaction repository's HEAD cannot redirect it.
validate_transaction_commit "$current_commit" \
    || fail transaction_changed_before_push
write_receipt pushing push "$current_commit" || fail transaction_receipt_write_failed
push_status=0
txn_git push --porcelain "$QWEN_PUBLISH_EXPECTED_REMOTE_URL" \
    "$current_commit:refs/heads/$branch" >/dev/null 2>&1 || push_status=$?
remote_after_push=$(read_remote_head 2>/dev/null || true)
if [[ $remote_after_push != "$current_commit" ]]; then
    write_receipt failed push "$current_commit" || true
    fail push_outcome_ambiguous
fi
validate_transaction_commit "$current_commit" || fail remote_tree_invalid
write_receipt published verified "$current_commit" || fail transaction_receipt_write_failed
trap - EXIT INT TERM
flock -u 9
lock_owned=0
printf '{"commit":"%s","push_status":%s,"state":"published","tasks":2499}\n' \
    "$current_commit" "$push_status"
