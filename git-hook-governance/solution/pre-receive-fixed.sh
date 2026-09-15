#!/bin/bash
# Pre-receive hook for repository governance policy enforcement
# Reads .repo-policy from the incoming push and enforces configured rules.


ZERO="0000000000000000000000000000000000000000"
POLICY_FILE=".repo-policy"
EXIT_CODE=0

# Read all ref updates into an array
declare -a UPDATES
while IFS=' ' read -r oldrev newrev refname; do
    UPDATES+=("$oldrev $newrev $refname")
done

# Find a valid commit to read policy from (prefer branch updates)
POLICY_REF=""
for update in "${UPDATES[@]}"; do
    read -r old new ref <<< "$update"
    if [[ "$new" != "$ZERO" && "$ref" == refs/heads/* ]]; then
        POLICY_REF="$new"
        break
    fi
done

# Fallback: for tag pushes, dereference the tag to get a commit
if [[ -z "$POLICY_REF" ]]; then
    for update in "${UPDATES[@]}"; do
        read -r old new ref <<< "$update"
        if [[ "$new" != "$ZERO" ]]; then
            POLICY_REF=$(git rev-parse "$new^{commit}" 2>/dev/null) && break
        fi
    done
fi

# Read policy from the pushed tree, falling back to HEAD
read_policy() {
    if [[ -n "$POLICY_REF" ]]; then
        git cat-file -p "${POLICY_REF}:${POLICY_FILE}" 2>/dev/null && return
    fi
    # Fallback: read from the repo's current HEAD
    git cat-file -p "HEAD:${POLICY_FILE}" 2>/dev/null
}

POLICY="$(read_policy)"

# Get all values for a key in a section
get_policy_values() {
    local section="$1"
    local key="$2"
    local in_section=0

    while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue

        if [[ "$line" =~ ^\[([a-zA-Z0-9_-]+)\] ]]; then
            if [[ "${BASH_REMATCH[1]}" == "$section" ]]; then
                in_section=1
            else
                in_section=0
            fi
            continue
        fi

        if [[ $in_section -eq 1 && "$line" =~ ^[[:space:]]*${key}[[:space:]]*=[[:space:]]*(.*) ]]; then
            local val="${BASH_REMATCH[1]}"
            # Trim trailing whitespace
            val="${val%"${val##*[![:space:]]}"}"
            echo "$val"
        fi
    done <<< "$POLICY"
}

# Get single value for a key in a section
get_policy_value() {
    get_policy_values "$1" "$2" | tail -1
}

# Match a string against a glob pattern using bash pattern matching
# IMPORTANT: the pattern variable must NOT be quoted on the RHS of ==
ref_matches_pattern() {
    local ref="$1"
    local pattern="$2"
    local branch="${ref#refs/heads/}"
    # Unquoted $pattern enables glob matching: release/* matches release/v1.0
    [[ "$branch" == $pattern ]]
}

# Match a filename against a file glob pattern
file_matches_pattern() {
    local filepath="$1"
    local pattern="$2"
    local filename
    filename=$(basename "$filepath")

    if [[ "$pattern" == */* ]]; then
        [[ "$filepath" == $pattern ]]
    else
        [[ "$filename" == $pattern ]]
    fi
}

# ── Protected Branches ──────────────────────────────────────────────

check_protected_branches() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$refname" != refs/heads/* ]] && return 0

    local patterns
    patterns=$(get_policy_values "protected-branches" "pattern")
    [[ -z "$patterns" ]] && return 0

    local is_protected=0
    while IFS= read -r pattern; do
        [[ -z "$pattern" ]] && continue
        if ref_matches_pattern "$refname" "$pattern"; then
            is_protected=1
            break
        fi
    done <<< "$patterns"

    [[ $is_protected -eq 0 ]] && return 0

    local branch="${refname#refs/heads/}"

    if [[ "$newrev" == "$ZERO" ]]; then
        echo "POLICY VIOLATION: Cannot delete protected branch '$branch'" >&2
        return 1
    fi

    if [[ "$oldrev" != "$ZERO" ]]; then
        if ! git merge-base --is-ancestor "$oldrev" "$newrev" 2>/dev/null; then
            echo "POLICY VIOLATION: Non-fast-forward push to protected branch '$branch' is not allowed" >&2
            return 1
        fi
    fi

    return 0
}

# ── Commit Messages ─────────────────────────────────────────────────

check_commit_messages() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$refname" != refs/heads/* ]] && return 0
    [[ "$newrev" == "$ZERO" ]] && return 0

    local regex
    regex=$(get_policy_value "commit-message" "regex")
    [[ -z "$regex" ]] && return 0

    local commits
    if [[ "$oldrev" == "$ZERO" ]]; then
        # New branch: only check commits NOT reachable from any existing ref
        local exclude_args=""
        while IFS= read -r existing_ref; do
            [[ -z "$existing_ref" ]] && continue
            exclude_args="$exclude_args --not $existing_ref"
        done < <(git for-each-ref --format='%(objectname)' refs/)
        commits=$(git rev-list "$newrev" $exclude_args 2>/dev/null)
    else
        commits=$(git rev-list "${oldrev}..${newrev}" 2>/dev/null)
    fi
    [[ -z "$commits" ]] && return 0

    local result=0
    while IFS= read -r commit; do
        [[ -z "$commit" ]] && continue
        local msg
        msg=$(git log -1 --format='%s' "$commit" 2>/dev/null)
        if ! echo "$msg" | grep -qP "$regex"; then
            echo "POLICY VIOLATION: Commit ${commit:0:12} has invalid message: '$msg'" >&2
            echo "  Must match: $regex" >&2
            result=1
        fi
    done <<< "$commits"

    return $result
}

# ── File Size Limits ─────────────────────────────────────────────────

check_file_sizes() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$newrev" == "$ZERO" ]] && return 0
    [[ "$refname" != refs/heads/* ]] && return 0

    local default_limit
    default_limit=$(get_policy_value "file-size-limit" "default")
    [[ -z "$default_limit" ]] && return 0

    # Collect per-pattern size overrides from the policy
    local -a override_pats=()
    local -a override_vals=()
    local in_section=0
    while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue
        if [[ "$line" =~ ^\[([a-zA-Z0-9_-]+)\] ]]; then
            [[ "${BASH_REMATCH[1]}" == "file-size-limit" ]] && in_section=1 || in_section=0
            continue
        fi
        if [[ $in_section -eq 1 && "$line" =~ ^[[:space:]]*([^=[:space:]]+)[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            local pat="${BASH_REMATCH[1]}"
            [[ "$pat" == "default" ]] && continue
            override_pats+=("$pat")
            override_vals+=("${BASH_REMATCH[2]}")
        fi
    done <<< "$POLICY"

    # Get changed/added files via diff-tree
    local diff_output
    if [[ "$oldrev" == "$ZERO" ]]; then
        local empty_tree
        empty_tree=$(git hash-object -t tree /dev/null)
        diff_output=$(git diff-tree -r "$empty_tree" "$newrev" 2>/dev/null)
    else
        diff_output=$(git diff-tree -r "$oldrev" "$newrev" 2>/dev/null)
    fi
    [[ -z "$diff_output" ]] && return 0

    local result=0
    while IFS=$'\t' read -r info filepath; do
        [[ -z "$filepath" ]] && continue
        local new_oid status
        read -r _ _ _ new_oid status <<< "$info"

        # Skip deletions
        [[ "$status" == D* ]] && continue
        [[ "$new_oid" == "$ZERO" ]] && continue

        # Determine the applicable limit
        local limit="$default_limit"
        local i
        for (( i=0; i<${#override_pats[@]}; i++ )); do
            if file_matches_pattern "$filepath" "${override_pats[$i]}"; then
                limit="${override_vals[$i]}"
            fi
        done

        # Check blob size
        local blob_size
        blob_size=$(git cat-file -s "$new_oid" 2>/dev/null)
        if [[ -n "$blob_size" && "$blob_size" -gt "$limit" ]]; then
            echo "POLICY VIOLATION: File '$filepath' size ${blob_size} bytes exceeds limit of ${limit} bytes" >&2
            result=1
        fi
    done <<< "$diff_output"

    return $result
}

# ── Forbidden Files ──────────────────────────────────────────────────

check_forbidden_files() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$newrev" == "$ZERO" ]] && return 0
    [[ "$refname" != refs/heads/* ]] && return 0

    local patterns
    patterns=$(get_policy_values "forbidden-files" "pattern")
    [[ -z "$patterns" ]] && return 0

    # Get added/modified files
    local diff_output
    if [[ "$oldrev" == "$ZERO" ]]; then
        local empty_tree
        empty_tree=$(git hash-object -t tree /dev/null)
        diff_output=$(git diff-tree -r "$empty_tree" "$newrev" 2>/dev/null)
    else
        diff_output=$(git diff-tree -r "$oldrev" "$newrev" 2>/dev/null)
    fi
    [[ -z "$diff_output" ]] && return 0

    local result=0
    while IFS=$'\t' read -r info filepath; do
        [[ -z "$filepath" ]] && continue
        local status
        read -r _ _ _ _ status <<< "$info"
        # Skip deletions
        [[ "$status" == D* ]] && continue

        while IFS= read -r pattern; do
            [[ -z "$pattern" ]] && continue
            if file_matches_pattern "$filepath" "$pattern"; then
                echo "POLICY VIOLATION: File '$filepath' matches forbidden pattern '$pattern'" >&2
                result=1
                break
            fi
        done <<< "$patterns"
    done <<< "$diff_output"

    return $result
}

# ── Merge Policy ─────────────────────────────────────────────────────

check_merge_policy() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$refname" != refs/heads/* ]] && return 0
    [[ "$newrev" == "$ZERO" ]] && return 0

    local require_linear
    require_linear=$(get_policy_value "merge-policy" "require-linear-history")
    [[ "$require_linear" != "true" ]] && return 0

    # Only applies to protected branches
    local patterns
    patterns=$(get_policy_values "protected-branches" "pattern")
    [[ -z "$patterns" ]] && return 0

    local is_protected=0
    while IFS= read -r pattern; do
        [[ -z "$pattern" ]] && continue
        if ref_matches_pattern "$refname" "$pattern"; then
            is_protected=1
            break
        fi
    done <<< "$patterns"
    [[ $is_protected -eq 0 ]] && return 0

    local branch="${refname#refs/heads/}"

    # Find merge commits in the range
    local merges
    if [[ "$oldrev" == "$ZERO" ]]; then
        local exclude_args=""
        while IFS= read -r existing_ref; do
            [[ -z "$existing_ref" ]] && continue
            exclude_args="$exclude_args --not $existing_ref"
        done < <(git for-each-ref --format='%(objectname)' refs/)
        merges=$(git rev-list --merges "$newrev" $exclude_args 2>/dev/null)
    else
        merges=$(git rev-list --merges "${oldrev}..${newrev}" 2>/dev/null)
    fi

    [[ -z "$merges" ]] && return 0

    local result=0
    while IFS= read -r merge_commit; do
        [[ -z "$merge_commit" ]] && continue
        echo "POLICY VIOLATION: Merge commit ${merge_commit:0:12} not allowed on protected branch '$branch' (linear history required)" >&2
        result=1
    done <<< "$merges"

    return $result
}

# ── Tag Policy ───────────────────────────────────────────────────────

check_tag_policy() {
    local oldrev="$1" newrev="$2" refname="$3"

    [[ "$refname" != refs/tags/* ]] && return 0

    local tagname="${refname#refs/tags/}"

    if [[ "$newrev" == "$ZERO" ]]; then
        local no_delete
        no_delete=$(get_policy_value "tag-policy" "no-delete")
        if [[ "$no_delete" == "true" ]]; then
            echo "POLICY VIOLATION: Deleting tag '$tagname' is not allowed" >&2
            return 1
        fi
        return 0
    fi

    if [[ "$oldrev" == "$ZERO" ]]; then
        local require_annotated
        require_annotated=$(get_policy_value "tag-policy" "require-annotated")
        if [[ "$require_annotated" == "true" ]]; then
            local obj_type
            obj_type=$(git cat-file -t "$newrev" 2>/dev/null)
            if [[ "$obj_type" != "tag" ]]; then
                echo "POLICY VIOLATION: Tag '$tagname' must be annotated (use 'git tag -a' or 'git tag -s')" >&2
                return 1
            fi
        fi
    fi

    return 0
}

# ── Main loop ────────────────────────────────────────────────────────

for update in "${UPDATES[@]}"; do
    read -r oldrev newrev refname <<< "$update"

    check_protected_branches "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_commit_messages "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_file_sizes "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_forbidden_files "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_merge_policy "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_tag_policy "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
done

exit $EXIT_CODE
