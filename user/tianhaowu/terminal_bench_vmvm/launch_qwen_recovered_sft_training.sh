#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() {
    printf '{"code":"%s","state":"error"}\n' "$1" >&2
    exit 2
}

[[ $# == 1 ]] || fail arguments_invalid
mode=$1
[[ $mode == check || $mode == dry-run || $mode == launch ]] || fail arguments_invalid

workflow=$(realpath -e -- "$(dirname -- "${BASH_SOURCE[0]}")")
project=$(realpath -e -- "$workflow/../../..")
config="$project/user/tianhaowu/fair-sc-3/configs/sft/nemotron_super_120b_qwen_recovered_v6_262144_cp2_ep8_1epoch.toml"
config_sha256=5d04975942c02660598ffc83965c76c32b4a0306d79b579121c2fdc0cb99d5be
runtime=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-qwen-recovered-sft-65cbf770
runtime_revision=65cbf770f5b81d3745c78d2f74c227eab04cd071
renderer_revision=044d9e2541f6a911cacae9da353fc063911ef1f8
export_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/qwen-recovered-v6-pass-only-65cbf770-rendered256k-v1
attestation="$export_root/sft-render-preflight-v2.json"
attestation_sha256=c3f129e1019963c6e8c6c6e7dec2b4e625131bf41dc76f1cf25246e2a8fffb44
tokenizer=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/tokenizers/nemotron3_super_120b_d51eab0_v1
uv_environment=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
uv_bin=/storage/home/tianhaowu/.local/x86_64/bin/uv

check_regular() {
    local path=$1
    local bytes=$2
    local digest=$3
    local mode_bits=$4
    [[ -f $path && ! -L $path ]] || fail artifact_invalid
    [[ $(stat -c '%s' -- "$path") == "$bytes" \
        && $(stat -c '%a' -- "$path") == "$mode_bits" \
        && $(sha256sum -- "$path" | cut -d' ' -f1) == "$digest" ]] \
        || fail artifact_identity_mismatch
}

[[ -f $config && ! -L $config \
    && $(sha256sum -- "$config" | cut -d' ' -f1) == "$config_sha256" ]] \
    || fail config_identity_mismatch
[[ $(realpath -e -- "$runtime") == "$runtime" \
    && $(git -C "$runtime" rev-parse --show-toplevel) == "$runtime" \
    && $(git -C "$runtime" rev-parse HEAD) == "$runtime_revision" \
    && $(git -C "$runtime" rev-parse --abbrev-ref HEAD) == HEAD \
    && -z $(git -C "$runtime" status --porcelain=v1 --untracked-files=all) \
    && $(git -C "$runtime/deps/renderers" rev-parse HEAD) == "$renderer_revision" \
    && -z $(git -C "$runtime/deps/renderers" status --porcelain=v1 --untracked-files=all) ]] \
    || fail runtime_identity_mismatch

check_regular "$attestation" 4941 "$attestation_sha256" 600
check_regular "$export_root/manifest.json" 8566 b8e8490efa5791cf52bff87936bfb48821f4938ebea8c016d52afab25c9941a8 600
check_regular "$export_root/target-rendering-contract.json" 831 305d66d12152b6de0f045a4fff3bd53adaaac173bcf8bbdc766efe4ceab3e981 600
check_regular "$export_root/task-split.json" 114502 1cd856c925b2188916b1152d07e5c0fd96e045bd8758e2a16528d616b45ffdb9 600
check_regular "$export_root/train/train.jsonl" 6654051979 b374607dfd7588779a4bb5925c84401b874cca5b0d64722286ef283250876525 600
check_regular "$export_root/validation/train.jsonl" 532861990 63448fa1c20afb22db1d24d2bb9e2e821731e2e209d041f4f7922e39297a766f 600

[[ -d $tokenizer && ! -L $tokenizer && $(stat -c '%a' -- "$tokenizer") == 500 ]] \
    || fail tokenizer_snapshot_invalid
check_regular "$tokenizer/chat_template.jinja" 10771 575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a 400
check_regular "$tokenizer/tokenizer.json" 17077484 623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7 400
check_regular "$tokenizer/tokenizer_config.json" 392 cf20ad4fec2526f39c940a05df88f164b2af587edffb352e2522792cdc593b8b 400

jq -e \
    --arg root "$export_root" \
    --arg project_revision "$runtime_revision" \
    --arg renderer_revision "$renderer_revision" '
    .schema_version == 2
    and .kind == "prime-rl-sft-render-preflight"
    and .expected_require_exact_provider_json == true
    and .export.root == $root
    and .export.manifest.sha256 == "b8e8490efa5791cf52bff87936bfb48821f4938ebea8c016d52afab25c9941a8"
    and .export.artifacts["train/train.jsonl"].sha256 == "b374607dfd7588779a4bb5925c84401b874cca5b0d64722286ef283250876525"
    and .export.artifacts["validation/train.jsonl"].sha256 == "63448fa1c20afb22db1d24d2bb9e2e821731e2e209d041f4f7922e39297a766f"
    and .code.project_revision == $project_revision
    and .code.renderer_repository_revision == $renderer_revision
    and .rendering.rows == 41125
    and .rendering.splits.train.rows == 38493
    and .rendering.splits.validation.rows == 2632
    and .rendering.max_rendered_tokens == 262130
    and .rendering.reasoning_fields_rendered == .rendering.nonempty_reasoning_fields
    and .rendering.nonempty_reasoning_fields == 825690
    and .source_validation.max_sequence_tokens == 262144
    and .source_validation.require_clean_stop == true
    and .source_validation.require_exact_provider_json == true
    and .source_validation.require_model_io == true
    and .source_validation.require_reasoning == true
    and .source_validation.require_request_graph_match == true
    and .target_rendering.max_sequence_tokens == 262144
    and .target_rendering.pack_function == "fixed_stack"
    and .target_rendering.loss_mask == {"assistant":true,"system":false,"tool":false,"user":false}
    and .target_rendering.tokenizer.revision == "d51eab0d1f979ebc26b546e634a04f450d99158e"
    and .target_rendering.renderer.repository_revision == $renderer_revision
    and .tokenizer_snapshot.tree.sha256 == "6e82696905f27ce4a339468accfd19d347c7f5c8c08bac688196f49a010c89eb"
' "$attestation" >/dev/null || fail attestation_contract_mismatch

if [[ $mode == check ]]; then
    printf '{"attestation_sha256":"%s","state":"validated"}\n' "$attestation_sha256"
    exit 0
fi

[[ $(uname -m) == x86_64 \
    && -x $uv_bin \
    && -x $uv_environment/bin/python ]] \
    || fail training_runtime_unavailable
export UV_PROJECT_ENVIRONMENT=$uv_environment
export PRIME_RL_SFT_PREFLIGHT_WORKERS=8
cd "$runtime"

if [[ $mode == dry-run ]]; then
    exec "$uv_bin" run --no-sync sft @ "$config" --dry-run
fi

[[ -n ${TMUX:-} && -n ${TMUX_PANE:-} \
    && $(tmux display-message -p -t "$TMUX_PANE" '#S:#W.#P') == swebench_vmvm:Launcher.0 ]] \
    || fail launcher_pane_mismatch
exec "$uv_bin" run --no-sync sft @ "$config"
