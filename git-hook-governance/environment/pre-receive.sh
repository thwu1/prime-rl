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

# Find a valid new-oid to read policy from
POLICY_REF=""
for update in "${UPDATES[@]}"; do
    read -r old new ref <<< "$update"
    if [[ "$new" != "$ZERO" && "$ref" == refs/heads/* ]]; then
        POLICY_REF="$new"
        break
    fi
done

# Read policy content from the pushed tree
# NOTE: Only reads from POLICY_REF; does not handle cases where
# POLICY_REF is empty (e.g. tag-only or deletion-only pushes).
read_policy() {
    if [[ -z "$POLICY_REF" ]]; then
        return
    fi
    git cat-file -p "${POLICY_REF}:${POLICY_FILE}" 2>/dev/null
}

POLICY="$(read_policy)"

# Get all values for a key in a section
# Usage: get_policy_values "section" "key"
get_policy_values() {
    local section="$1"
    local key="$2"
    local in_section=0

    echo "$POLICY" | while IFS= read -r line; do
        # Skip comments and blank lines
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
            echo "${BASH_REMATCH[1]}"
        fi
    done
}

# Get single value for a key in a section
get_policy_value() {
    get_policy_values "$1" "$2" | tail -1
}

# Check if a ref name matches a branch pattern
ref_matches_pattern() {
    local ref="$1"
    local pattern="$2"
    local branch="${ref#refs/heads/}"

    [[ "$branch" == "$pattern" ]]
}

# Check protected branches policy
check_protected_branches() {
    local oldrev="$1"
    local newrev="$2"
    local refname="$3"

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

    # Check for deletion
    if [[ "$newrev" == "$ZERO" ]]; then
        echo "POLICY VIOLATION: Cannot delete protected branch '$branch'" >&2
        return 1
    fi

    # Check for non-fast-forward (only if not a new branch)
    if [[ "$oldrev" != "$ZERO" ]]; then
        if ! git merge-base --is-ancestor "$oldrev" "$newrev" 2>/dev/null; then
            echo "POLICY VIOLATION: Non-fast-forward push to protected branch '$branch' is not allowed" >&2
            return 1
        fi
    fi

    return 0
}

# Check commit message policy
check_commit_messages() {
    local oldrev="$1"
    local newrev="$2"
    local refname="$3"

    [[ "$refname" != refs/heads/* ]] && return 0
    [[ "$newrev" == "$ZERO" ]] && return 0

    local regex
    regex=$(get_policy_value "commit-message" "regex")
    [[ -z "$regex" ]] && return 0

    local range
    if [[ "$oldrev" == "$ZERO" ]]; then
        # New branch: enumerate all commits on this branch
        range="$newrev"
    else
        range="${oldrev}..${newrev}"
    fi

    local commits
    commits=$(git rev-list "$range" 2>/dev/null)
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

# TODO: check_file_sizes is not implemented
# Should enforce [file-size-limit] policy

# TODO: check_forbidden_files is not implemented
# Should enforce [forbidden-files] policy

# TODO: check_merge_policy is not implemented
# Should enforce [merge-policy] policy

# Check tag policy
check_tag_policy() {
    local oldrev="$1"
    local newrev="$2"
    local refname="$3"

    [[ "$refname" != refs/tags/* ]] && return 0

    local tagname="${refname#refs/tags/}"

    # Check for tag deletion
    if [[ "$newrev" == "$ZERO" ]]; then
        local no_delete
        no_delete=$(get_policy_value "tag-policy" "no-delete")
        if [[ "$no_delete" == "true" ]]; then
            echo "POLICY VIOLATION: Deleting tag '$tagname' is not allowed" >&2
            return 1
        fi
    fi

    # Check for annotated tags (new tag only)
    if [[ "$newrev" != "$ZERO" && "$oldrev" == "$ZERO" ]]; then
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

# Process each ref update
for update in "${UPDATES[@]}"; do
    read -r oldrev newrev refname <<< "$update"

    check_protected_branches "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_commit_messages "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
    check_tag_policy "$oldrev" "$newrev" "$refname" || EXIT_CODE=1
done

exit $EXIT_CODE
