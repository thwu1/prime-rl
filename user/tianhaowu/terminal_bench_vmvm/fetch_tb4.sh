#!/usr/bin/env bash
# Fetch the immutable official Terminal-Bench 4.0.0 task corpus.
set -euo pipefail

repository=${TB4_REPOSITORY:-https://github.com/harbor-framework/terminal-bench.git}
revision=${TB4_REVISION:-452bf305c6daa62fc59061d22133a7cbc7c1572e}
target=${TB4_CHECKOUT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-v4.0.0}
prebuilt_target=${TB4_PREBUILT:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0}
download_dir=${TB4_DOWNLOADS:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads}
archive="$download_dir/terminal-bench-prebuilt-v4.0.0.tar.gz"
archive_sha256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e

if [[ -e "$target" ]]; then
    if [[ ! -d "$target/.git" ]]; then
        printf 'Refusing to replace non-git path: %s\n' "$target" >&2
        exit 2
    fi
    actual=$(git -C "$target" rev-parse HEAD)
    if [[ "$actual" != "$revision" ]]; then
        printf 'Existing checkout is at %s, expected %s: %s\n' "$actual" "$revision" "$target" >&2
        exit 2
    fi
else
    mkdir -p "$(dirname "$target")"
    git clone --filter=blob:none --no-checkout "$repository" "$target"
    git -C "$target" fetch --depth=1 origin "$revision"
    git -C "$target" checkout --detach "$revision"
fi

actual=$(git -C "$target" rev-parse HEAD)
count=$(find "$target/tasks" -mindepth 2 -maxdepth 2 -name task.toml -type f | wc -l)
if [[ "$actual" != "$revision" || "$count" -ne 66 ]]; then
    printf 'TB4 integrity check failed: revision=%s tasks=%s\n' "$actual" "$count" >&2
    exit 2
fi

mkdir -p "$download_dir"
if [[ ! -f "$archive" ]] || [[ "$(sha256sum "$archive" | cut -d' ' -f1)" != "$archive_sha256" ]]; then
    gh release download v4.0.0 \
        --repo harbor-framework/terminal-bench \
        --pattern terminal-bench-prebuilt-v4.0.0.tar.gz \
        --dir "$download_dir" \
        --clobber
fi
actual_archive_sha256=$(sha256sum "$archive" | cut -d' ' -f1)
if [[ "$actual_archive_sha256" != "$archive_sha256" ]]; then
    printf 'TB4 prebuilt archive digest mismatch: got %s expected %s\n' \
        "$actual_archive_sha256" "$archive_sha256" >&2
    exit 2
fi
if [[ ! -d "$prebuilt_target/tasks" ]]; then
    if [[ -e "$prebuilt_target" ]]; then
        printf 'Refusing to replace incomplete prebuilt path: %s\n' "$prebuilt_target" >&2
        exit 2
    fi
    mkdir -p "$prebuilt_target"
    tar --warning=no-unknown-keyword -xzf "$archive" -C "$prebuilt_target"
fi
prebuilt_count=$(find "$prebuilt_target/tasks" -mindepth 2 -maxdepth 2 -name task.toml -type f | wc -l)
declared_images=$(grep -Rl --include=task.toml 'docker_image' "$prebuilt_target/tasks" | wc -l)
if [[ "$prebuilt_count" -ne 66 || "$declared_images" -ne 66 ]]; then
    printf 'TB4 prebuilt integrity check failed: tasks=%s image-configs=%s\n' \
        "$prebuilt_count" "$declared_images" >&2
    exit 2
fi
printf 'TB4 ready: revision=%s source_tasks=%s prebuilt_tasks=%s path=%s/tasks\n' \
    "$actual" "$count" "$prebuilt_count" "$prebuilt_target"
