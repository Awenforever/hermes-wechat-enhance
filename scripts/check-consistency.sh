#!/usr/bin/env bash
# ============================================================================
# check-consistency.sh — Hermes WeChat Enhance Skill File Consistency Audit
# ============================================================================
#
# Audits the hermes-wechat-enhance skill directory for file consistency:
#   1. Every .patch file in patches/ is referenced in CUSTOMIZATIONS.md,
#      README.md, and SKILL.md
#   2. Every patch mentioned in those docs actually exists in patches/
#   3. Every reference listed in SKILL.md exists in references/
#   4. Orphan .patch files outside patches/ (warning only)
#
# Usage:
#   ./scripts/check-consistency.sh
#   # or from skill root:
#   bash scripts/check-consistency.sh
#
# Exit codes:
#   0 = All checks passed (no errors, no warnings)
#   1 = Warnings only (orphan patches, minor issues)
#   2 = Errors (missing patches, broken references)
#
# Path detection:
#   Determines SKILL_DIR from the script's own location:
#   - If script is in scripts/ → SKILL_DIR = parent
#   - If script is in root/   → SKILL_DIR = same dir
# ============================================================================

set -euo pipefail

# ── Path detection ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$(basename "$0")"

if [[ "$SCRIPT_DIR" == */scripts ]]; then
    SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [[ "$SCRIPT_DIR" == */scripts/* ]]; then
    SKILL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
else
    SKILL_DIR="$SCRIPT_DIR"
fi

PATCHES_DIR="$SKILL_DIR/patches"
REFERENCES_DIR="$SKILL_DIR/references"

# ── Status tracking ──────────────────────────────────────────────────────────
ERRORS=0
WARNINGS=0
PASS=0
CHECK_NUM=0

# ── Helpers ──────────────────────────────────────────────────────────────────
green()  { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red()    { printf "\033[31m%s\033[0m\n" "$1"; }

pass()   { ((PASS++)) || true; }
warn()   { echo "  ⚠  $1"; yellow "  → $2"; ((WARNINGS++)) || true; }
fail()   { echo "  ✗  $1"; red    "  → $2"; ((ERRORS++))   || true; }

header()   { CHECK_NUM=$((CHECK_NUM + 1)); echo ""; echo "─── [$CHECK_NUM] $1 ───"; }
summary()  { echo ""; echo "═══ Summary ═══"; echo "  Passes:   $PASS"; echo "  Warnings: $WARNINGS"; echo "  Errors:   $ERRORS"; }

# Check if a string is in an array (by join+regex)
arr_contains() { local e; for e in "${@:2}"; do [[ "$e" == "$1" ]] && return 0; done; return 1; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo "============================================================"
echo " Hermes WeChat Enhance — Consistency Check"
echo "============================================================"
echo " Skill dir:  $SKILL_DIR"
echo " Patches:    $PATCHES_DIR"
echo " References: $REFERENCES_DIR"
echo ""

# ── Validate required directories exist ─────────────────────────────────────
if [[ ! -d "$SKILL_DIR" ]]; then
    echo "ERROR: Skill directory does not exist: $SKILL_DIR"
    exit 2
fi

# ── 1. Collect actual patch files from patches/ ─────────────────────────────
header "Collecting patch files from patches/"

declare -a ACTUAL_PATCHES=()
declare -a ACTUAL_PATCH_BASENAMES=()

if [[ -d "$PATCHES_DIR" ]]; then
    while IFS= read -r -d '' f; do
        basename_f="$(basename "$f")"
        if [[ "$basename_f" == *.patch ]]; then
            ACTUAL_PATCHES+=("$f")
            ACTUAL_PATCH_BASENAMES+=("$basename_f")
        fi
    done < <(find "$PATCHES_DIR" -maxdepth 1 -name '*.patch' -print0 2>/dev/null || true)
fi

if [[ ${#ACTUAL_PATCH_BASENAMES[@]} -eq 0 ]]; then
    fail "No .patch files found in patches/" "patches/ directory missing or empty"
fi

echo "  Found ${#ACTUAL_PATCH_BASENAMES[@]} .patch files in patches/:"
for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
    echo "    • $p"
done

# For archive/suffix patches, extract the base number (e.g., "001" from "001-*.v017.patch")
declare -a ACTUAL_PATCH_IDS=()
for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
    # Extract leading digits (patch number) from the filename
    id=$(echo "$p" | sed -n 's/^\([0-9]\{3\}\).*/\1/p')
    if [[ -n "$id" ]]; then
        arr_contains "$id" "${ACTUAL_PATCH_IDS[@]}" || ACTUAL_PATCH_IDS+=("$id")
    fi
done

echo "  Patch IDs: ${ACTUAL_PATCH_IDS[*]:-(none)}"
pass

# ── 2. Check patches/ files referenced in CUSTOMIZATIONS.md ─────────────────
header "CUSTOMIZATIONS.md → patches/ cross-reference"

CUSTOMIZATIONS="$SKILL_DIR/CUSTOMIZATIONS.md"
if [[ ! -f "$CUSTOMIZATIONS" ]]; then
    fail "CUSTOMIZATIONS.md not found" "Expected at $CUSTOMIZATIONS"
else
    # Extract all "Patch NNN" references from CUSTOMIZATIONS.md
    # Patterns: "Patch 001:", "Patch 001", "001", "patches/001-",
    # Also "005" in summary table, "002, 005" etc.
    declare -a CUSTOM_PATCH_REFS=()
    while IFS= read -r line; do
        # Extract numbers like "001", "002" from patch references
        nums=$(echo "$line" | grep -oE '\b[0-9]{3}\b' || true)
        for n in $nums; do
            # Skip numbers that are not patch IDs (like 539 for line counts, 470, etc.)
            # Patch IDs are 001-999 and typically appear near "Patch", "patches/", or standalone
            # But since CUSTOMIZATIONS has many numbers, let's be smarter
            if [[ "$n" =~ ^00[1-9]$|^0[1-9][0-9]$ ]]; then
                arr_contains "$n" "${CUSTOM_PATCH_REFS[@]}" || CUSTOM_PATCH_REFS+=("$n")
            fi
        done
    done < <(grep -n -i 'patch' "$CUSTOMIZATIONS" 2>/dev/null || true)

    # Also check the summary table which lists "005" etc.
    while IFS= read -r line; do
        nums=$(echo "$line" | grep -oE '\b[0-9]{3}\b' || true)
        for n in $nums; do
            if [[ "$n" =~ ^00[1-9]$|^0[1-9][0-9]$ ]]; then
                arr_contains "$n" "${CUSTOM_PATCH_REFS[@]}" || CUSTOM_PATCH_REFS+=("$n")
            fi
        done
    done < <(grep -E '^\|.*\|' "$CUSTOMIZATIONS" 2>/dev/null || true)

    echo "  Patch IDs referenced in CUSTOMIZATIONS.md: ${CUSTOM_PATCH_REFS[*]:-(none)}"

    # Check: every actual patch ID is in CUSTOM_PATCH_REFS
    for pid in "${ACTUAL_PATCH_IDS[@]}"; do
        if ! arr_contains "$pid" "${CUSTOM_PATCH_REFS[@]}"; then
            warn "Patch $pid exists in patches/ but is not referenced in CUSTOMIZATIONS.md" \
                 "Consider adding documentation for patch $pid"
        else
            pass
        fi
    done

    # Check: every CUSTOM_PATCH_REF has a corresponding patch file
    for ref in "${CUSTOM_PATCH_REFS[@]}"; do
        # Check if any actual patch file starts with this ID
        found=0
        for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
            if [[ "$p" == "$ref"-* ]]; then
                found=1
                break
            fi
        done
        if [[ $found -eq 0 ]]; then
            fail "CUSTOMIZATIONS.md references patch '$ref' but no matching .patch file found" \
                 "Missing: ${ref}-*.patch in patches/"
        else
            pass
        fi
    done
fi

# ── 3. Check patches/ files referenced in README.md ─────────────────────────
header "README.md → patches/ cross-reference"

README="$SKILL_DIR/README.md"
if [[ ! -f "$README" ]]; then
    fail "README.md not found" "Expected at $README"
else
    declare -a README_PATCH_REFS=()
    while IFS= read -r line; do
        # Look for patch file references like "001-weixin-..."
        nums=$(echo "$line" | grep -oP '\b\d{3}-weixin[-a-z]*\.patch\b' | grep -oP '^\d{3}' || true)
        for n in $nums; do
            arr_contains "$n" "${README_PATCH_REFS[@]}" || README_PATCH_REFS+=("$n")
        done
    done < <(cat "$README" 2>/dev/null || true)

    # Also check for references to patch numbers in code blocks or text
    while IFS= read -r line; do
        if echo "$line" | grep -qP '(patch|patches)'; then
            nums=$(echo "$line" | grep -oP '\b(00[1-9]|0[1-9][0-9])\b' || true)
            for n in $nums; do
                arr_contains "$n" "${README_PATCH_REFS[@]}" || README_PATCH_REFS+=("$n")
            done
        fi
    done < <(cat "$README" 2>/dev/null || true)

    echo "  Patches referenced in README.md: ${README_PATCH_REFS[*]:-(none)}"

    # Check: every actual non-archived patch (without .v017 etc) is in README references
    for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
        # Skip archived patches (like *.v017.patch) from this check
        if echo "$p" | grep -q '\.v[0-9]\{3\}\.'; then
            continue
        fi
        id=$(echo "$p" | sed -n 's/^\([0-9]\{3\}\).*/\1/p')
        if [[ -n "$id" ]] && ! arr_contains "$id" "${README_PATCH_REFS[@]}"; then
            warn "Current patch $id ($p) not directly referenced in README.md" \
                 "README may need updating to mention patch $id"
        else
            pass
        fi
    done

    # Check: every README patch reference has a file
    for ref in "${README_PATCH_REFS[@]}"; do
        found=0
        for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
            if [[ "$p" == "$ref"-* ]]; then
                found=1
                break
            fi
        done
        if [[ $found -eq 0 ]]; then
            warn "README.md references patch '$ref' but no matching .patch file found in patches/" \
                 "Missing: ${ref}-*.patch"
        else
            pass
        fi
    done
fi

# ── 4. Check patches/ files in SKILL.md ─────────────────────────────────────
header "SKILL.md → patches/ cross-reference"

SKILL="$SKILL_DIR/SKILL.md"
if [[ ! -f "$SKILL" ]]; then
    fail "SKILL.md not found" "Expected at $SKILL"
else
    declare -a SKILL_PATCH_REFS=()
    # Extract patch filenames from SKILL.md like "patches/001-weixin-continue-hook.patch"
    while IFS= read -r line; do
        fname=$(echo "$line" | grep -oP 'patches/\K[0-9]{3}[-a-zA-Z0-9_.]+\.patch' || true)
        if [[ -n "$fname" ]]; then
            id=$(echo "$fname" | sed -n 's/^\([0-9]\{3\}\).*/\1/p')
            if [[ -n "$id" ]]; then
                arr_contains "$id" "${SKILL_PATCH_REFS[@]}" || SKILL_PATCH_REFS+=("$id")
            fi
        fi
    done < <(cat "$SKILL" 2>/dev/null || true)

    # Also look for pattern like "001:" or "Patch 001" in SKILL.md
    while IFS= read -r line; do
        if echo "$line" | grep -qiP '(patch|patches)'; then
            nums=$(echo "$line" | grep -oP '\b(00[1-9]|0[1-9][0-9])\b' || true)
            for n in $nums; do
                arr_contains "$n" "${SKILL_PATCH_REFS[@]}" || SKILL_PATCH_REFS+=("$n")
            done
        fi
    done < <(cat "$SKILL" 2>/dev/null || true)

    echo "  Patches referenced in SKILL.md: ${SKILL_PATCH_REFS[*]:-(none)}"

    # Check: every non-archived actual patch is in SKILL.md
    for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
        if echo "$p" | grep -q '\.v[0-9]\{3\}\.'; then
            continue
        fi
        id=$(echo "$p" | sed -n 's/^\([0-9]\{3\}\).*/\1/p')
        if [[ -n "$id" ]] && ! arr_contains "$id" "${SKILL_PATCH_REFS[@]}"; then
            warn "Current patch $id ($p) not directly referenced in SKILL.md" \
                 "SKILL.md may need updating to mention patch $id"
        else
            pass
        fi
    done

    # Check: every SKILL.md reference has a file
    for ref in "${SKILL_PATCH_REFS[@]}"; do
        found=0
        for p in "${ACTUAL_PATCH_BASENAMES[@]}"; do
            if [[ "$p" == "$ref"-* ]]; then
                found=1
                break
            fi
        done
        if [[ $found -eq 0 ]]; then
            warn "SKILL.md references patch '$ref' but no matching .patch file found in patches/" \
                 "Missing: ${ref}-*.patch"
        else
            pass
        fi
    done
fi

# ── 5. Check references/ files listed in SKILL.md ──────────────────────────
header "SKILL.md references/ → actual files cross-reference"

if [[ ! -d "$REFERENCES_DIR" ]]; then
    fail "references/ directory does not exist" "Expected at $REFERENCES_DIR"
else
    # Collect actual reference files
    declare -a ACTUAL_REFS=()
    while IFS= read -r -d '' f; do
        ACTUAL_REFS+=("$(basename "$f")")
    done < <(find "$REFERENCES_DIR" -maxdepth 1 -name '*.md' -print0 2>/dev/null || true)
    echo "  Actual references/ files (${#ACTUAL_REFS[@]}):"
    for r in "${ACTUAL_REFS[@]}"; do
        echo "    • $r"
    done

    # Extract references from SKILL.md: pattern like "references/architecture-analysis.md"
    declare -a SKILL_REF_REFS=()
    while IFS= read -r line; do
        refname=$(echo "$line" | grep -oP 'references/\K[-\w]+(?=\.md)' || true)
        if [[ -n "$refname" ]]; then
            arr_contains "${refname}.md" "${SKILL_REF_REFS[@]}" || SKILL_REF_REFS+=("${refname}.md")
        fi
    done < <(cat "$SKILL" 2>/dev/null || true)

    echo "  References mentioned in SKILL.md: ${SKILL_REF_REFS[*]:-(none)}"

    # Check: every SKILL.md reference exists in references/
    for ref in "${SKILL_REF_REFS[@]}"; do
        if [[ -f "$REFERENCES_DIR/$ref" ]]; then
            pass
        else
            warn "SKILL.md references '$ref' but file not found in references/" \
                 "Missing: references/$ref"
        fi
    done

    # Flag references not listed in SKILL.md
    for ref in "${ACTUAL_REFS[@]}"; do
        if ! arr_contains "$ref" "${SKILL_REF_REFS[@]}"; then
            pass
            # Not a warning — many reference files are not directly linked from SKILL.md Contents section
            # They may be linked deeper in the doc
        fi
    done

    # Check deep references to references/ in SKILL.md body
    declare -a SKILL_DEEP_REFS=()
    while IFS= read -r line; do
        refname=$(echo "$line" | grep -oP 'references/\K[-\w]+(?=\.md)' || true)
        if [[ -n "$refname" ]] && ! arr_contains "${refname}.md" "${SKILL_DEEP_REFS[@]}"; then
            SKILL_DEEP_REFS+=("${refname}.md")
        fi
    done < <(cat "$SKILL" 2>/dev/null || true)

    # Check each actual reference file is mentioned somewhere in SKILL.md
    for act in "${ACTUAL_REFS[@]}"; do
        found=0
        for sref in "${SKILL_DEEP_REFS[@]}"; do
            if [[ "$act" == "$sref" ]]; then
                found=1
                break
            fi
        done
        if [[ $found -eq 0 ]]; then
            # Check if the filename appears anywhere in SKILL.md as text
            basename_noext="${act%.md}"
            if grep -q "$basename_noext" "$SKILL" 2>/dev/null; then
                pass  # Referenced without the "references/" prefix
            else
                warn "Reference '$act' not mentioned in SKILL.md at all" \
                     "SKILL.md may need updating to document this reference"
            fi
        fi
    done
fi

# ── 6. Check for orphan .patch files outside patches/ ───────────────────────
header "Orphan .patch files outside patches/"

declare -a ORPHAN_PATCHES=()
while IFS= read -r -d '' f; do
    # Skip files in patches/ directory itself
    if [[ "$(dirname "$f")" != "$PATCHES_DIR" ]]; then
        ORPHAN_PATCHES+=("$f")
    fi
done < <(find "$SKILL_DIR" -name '*.patch' -print0 2>/dev/null || true)

if [[ ${#ORPHAN_PATCHES[@]} -gt 0 ]]; then
    for op in "${ORPHAN_PATCHES[@]}"; do
        rel="${op#$SKILL_DIR/}"
        warn "Orphan .patch file outside patches/: $rel" \
             "Move into patches/ or remove if unused"
    done
else
    echo "  No orphan .patch files found outside patches/."
    pass
fi

# ── 7. Validate CHANGELOG.md exists in patches/ ────────────────────────────
header "Patches directory completeness"

if [[ -f "$PATCHES_DIR/CHANGELOG.md" ]]; then
    pass
else
    warn "patches/CHANGELOG.md not found" \
         "Consider adding a CHANGELOG.md to track patch version history"
fi


# ── 8. Consolidated v0.18 Weixin patch contract ──────────────────────────────
header "Consolidated v0.18 Weixin patch contract"

EXPECTED_SERIES=$'003\n004\n006\n007\n008\n011'
ACTUAL_SERIES="$(grep -v '^[[:space:]]*#' "$PATCHES_DIR/series" | sed '/^[[:space:]]*$/d')"
if [[ "$ACTUAL_SERIES" == "$EXPECTED_SERIES" ]]; then
    pass
else
    fail "v0.18 patch series is not deterministic" "Expected 003 004 006 007 008 011"
fi

CONSOLIDATED_PATCH="$PATCHES_DIR/011-weixin-v018-consolidated.patch"
if [[ -f "$CONSOLIDATED_PATCH" ]]; then pass; else
    fail "Patch 011 is missing" "Restore the consolidated v0.18 Weixin patch"
fi

for marker in \
    HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1 \
    HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1 \
    HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1 \
    HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1 \
    HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1 \
    HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1 \
    HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1 \
    HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1 \
    WECHAT_ENHANCE_RELIABLE_DELIVERY_V2 \
    WECHAT_ENHANCE_REPLY_BUDGET_COMMIT_AFTER_ACK_V2 \
    WECHAT_ENHANCE_QUEUE_PEEK_COMMIT_V2 \
    WECHAT_ENHANCE_DELIVERY_ID_DEDUPE_V2
do
    if grep -q "$marker" "$CONSOLIDATED_PATCH"; then
        pass
    else
        fail "Patch 011 lacks $marker" "Regenerate patch 011 from official v0.18"
    fi
done

for required in \
    "$SKILL_DIR/scripts/manage-install-state.py" \
    "$SKILL_DIR/scripts/test-context-token-kernel-contract.py"
do
    if [[ -f "$required" ]]; then pass; else
        fail "Required file missing: $required" "Restore the file"
    fi
done

if grep -qi "slash command" "$README" && grep -qi "slash command" "$SKILL"; then
    pass
else
    fail "README/SKILL do not document slash-command exemption" "Update docs"
fi

# ── 9. Deterministic patch variant dispatch ──────────────────────────────────
header "Deterministic patch variant dispatch"

if grep -q "HERMES_WECHAT_PATCH_VARIANT_DISPATCH_V1" "$SKILL_DIR/scripts/install.sh"; then
    pass
else
    fail "Installer lacks patch variant dispatch marker" "Restore v0.18 dispatch"
fi

if grep -q 'v2026.7.1' "$SKILL_DIR/scripts/install.sh" \
   && grep -q 'v017.patch' "$SKILL_DIR/scripts/install.sh"; then
    pass
else
    fail "Installer does not explicitly separate v0.18 from v0.17 variants" \
         "Restore patch_matches_version"
fi


# ── 10. Portable hook import bootstrap ───────────────────────────────────────
header "Portable hook import bootstrap"

HOOK_HANDLER="$SKILL_DIR/hooks/hermes-wechat-enhance/handler.py"

if grep -q "WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2" "$HOOK_HANDLER"; then
    pass
else
    fail "Hook lacks portable import bootstrap marker" \
         "Restore WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2"
fi

for token in \
    HERMES_WECHAT_ENHANCE_SOURCE_DIR \
    HERMES_SKILLS_DIR \
    HERMES_HOME
do
    if grep -q "$token" "$HOOK_HANDLER"; then
        pass
    else
        fail "Hook bootstrap lacks $token support" \
             "Restore portable path resolution"
    fi
done

if grep -q 'Path(__file__).resolve().parents\[2\]' "$HOOK_HANDLER"; then
    pass
else
    fail "Hook bootstrap lacks path-derived fallback" \
         "Restore hook-relative skill discovery"
fi


# ── 11. Contract harness runtime initialization ───────────────────────────────
header "Contract harness runtime initialization"

KERNEL_TEST="$SKILL_DIR/scripts/test-context-token-kernel-contract.py"

if grep -q "TEST_WEIXIN_ADAPTER_REAL_INIT_V1" "$KERNEL_TEST"; then
    pass
else
    fail "Kernel test does not use real WeixinAdapter initialization" \
         "Restore TEST_WEIXIN_ADAPTER_REAL_INIT_V1"
fi

if grep -q "SYNTHETIC_ADAPTER_RUNTIME_INIT_OK" "$KERNEL_TEST"; then
    pass
else
    fail "Kernel test lacks adapter initialization preflight" \
         "Restore SYNTHETIC_ADAPTER_RUNTIME_INIT_OK"
fi


# ── 12. Idempotent hook deployment without residue ────────────────────────────
header "Idempotent hook deployment without residue"

INSTALLER="$SKILL_DIR/scripts/install.sh"
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"

if grep -q "WECHAT_ENHANCE_HOOK_IDEMPOTENT_NO_BACKUP_RESIDUE_V1" "$INSTALLER"; then
    pass
else
    fail "Installer lacks no-backup-residue hook marker" \
         "Restore deterministic hook deployment"
fi

if grep -q "normalized_tree_hash" "$INSTALLER"; then
    pass
else
    fail "Installer lacks normalized hook comparison" \
         "Restore normalized_tree_hash"
fi

if grep -q "before-install-" "$INSTALLER"; then
    fail "Installer still creates untracked timestamped hook backups" \
         "Use install-state snapshot as the only rollback source"
else
    pass
fi

if grep -q "TRANSIENT_TREE_PARTS" "$STATE_MANAGER" \
   && grep -q "__pycache__" "$STATE_MANAGER" \
   && grep -q "\\.pyc" "$STATE_MANAGER"; then
    pass
else
    fail "Install-state hook hash does not ignore runtime caches" \
         "Restore transient tree filtering"
fi


# ── 13. Pristine and legacy v0.18 source profiles ─────────────────────────────
header "Pristine and legacy v0.18 source profiles"

INSTALLER="$SKILL_DIR/scripts/install.sh"

if grep -q "HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1" "$INSTALLER"; then
    pass
else
    fail "Installer lacks v0.18 source-profile marker" \
         "Restore source-profile dispatch"
fi

for series in \
    series.pristine-v018 \
    series.legacy-v018 \
    series.hardened-v018
do
    if [[ -f "$PATCHES_DIR/$series" ]]; then
        pass
    else
        fail "Missing profile series: $series" \
             "Restore profile-specific series files"
    fi
done

if grep -qx '011' "$PATCHES_DIR/series.pristine-v018" \
   && grep -qx '012' "$PATCHES_DIR/series.legacy-v018"; then
    pass
else
    fail "Pristine/legacy Weixin patch routing is incorrect" \
         "Route pristine to 011 and legacy to 012"
fi

if [[ -f "$PATCHES_DIR/012-weixin-v018-legacy-upgrade.patch" ]]; then
    pass
else
    fail "Legacy upgrade patch 012 is missing" \
         "Restore patch 012"
fi

for marker in \
    HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1 \
    HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1 \
    HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1 \
    HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1
do
    if grep -q "$marker" "$PATCHES_DIR/012-weixin-v018-legacy-upgrade.patch"; then
        pass
    else
        fail "Patch 012 lacks $marker" "Regenerate legacy upgrade patch"
    fi
done


# ── 14. Version resolution from verified source profile ───────────────────────
header "Version resolution from verified source profile"

INSTALLER="$SKILL_DIR/scripts/install.sh"

if grep -q "HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1" "$INSTALLER"; then
    pass
else
    fail "Installer lacks verified source-profile version fallback" \
         "Restore version inference marker"
fi

if grep -q 'detect_version "$source_profile"' "$INSTALLER"; then
    pass
else
    fail "Installer resolves version before source profile" \
         "Detect source profile first"
fi

if grep -q "VERSION_SOURCE=verified-source-profile" "$INSTALLER" \
   && grep -q "VERSION_SOURCE=external-metadata" "$INSTALLER"; then
    pass
else
    fail "Installer does not report version provenance" \
         "Restore VERSION_SOURCE logging"
fi

if grep -q 'pristine-v018|legacy-v018|hardened-v018' "$INSTALLER"; then
    pass
else
    fail "Version fallback is not restricted to verified v0.18 profiles" \
         "Restrict version inference"
fi


# ── 15. Hermes v0.18 version-family normalization ─────────────────────────────
header "Hermes v0.18 version-family normalization"

INSTALLER="$SKILL_DIR/scripts/install.sh"

if grep -q "HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1" "$INSTALLER"; then
    pass
else
    fail "Installer lacks v0.18 version-family marker" \
         "Restore version-family normalization"
fi

if grep -q "normalize_version_family" "$INSTALLER"; then
    pass
else
    fail "Installer lacks normalize_version_family" \
         "Restore version alias mapping"
fi

for alias in \
    v2026.7.1 \
    v0.18.0 \
    v0.18
do
    if grep -q "$alias" "$INSTALLER"; then
        pass
    else
        fail "Installer lacks accepted version alias $alias" \
             "Restore v0.18 alias mapping"
    fi
done

if grep -q 'apply_patches "$patch_dir" "$version_family" "$source_profile"' "$INSTALLER"; then
    pass
else
    fail "Patch selection does not use normalized version family" \
         "Route patch selection through version_family"
fi


# ── 16. Transactional source state and fault injection ────────────────────────
header "Transactional source state and fault injection"

INSTALLER="$SKILL_DIR/scripts/install.sh"
UNINSTALLER="$SKILL_DIR/scripts/uninstall.sh"
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"

for marker in \
    HERMES_WECHAT_TRANSACTIONAL_SOURCE_STATE_V1 \
    HERMES_WECHAT_FAULT_INJECTION_TEST_V1
do
    if grep -q "$marker" "$INSTALLER"; then
        pass
    else
        fail "Installer lacks $marker" "Restore transaction contract"
    fi
done

if grep -q "before-source-install-" "$INSTALLER"; then
    fail "Installer still creates timestamped source backups" \
         "Use source snapshot only"
else
    pass
fi

if grep -q 'fault_inject after-source-install' "$INSTALLER" \
   && grep -q 'fault_inject after-gateway-patches' "$INSTALLER" \
   && grep -q 'fault_inject after-hook-install' "$INSTALLER"; then
    pass
else
    fail "Installer lacks deterministic fault stages" \
         "Restore fault injection points"
fi

if grep -q 'git config user\.' "$INSTALLER"; then
    fail "Installer mutates persistent Git identity" \
         "Use per-command git -c identity"
else
    pass
fi

if grep -q -- '--source "$CANONICAL_SOURCE_DIR"' "$INSTALLER" \
   && grep -q -- '--source "$CANONICAL_SOURCE_DIR"' "$UNINSTALLER"; then
    pass
else
    fail "Installer/uninstaller lack canonical source state" \
         "Restore --source integration"
fi

for token in \
    source_pre_hash \
    source_installed_hash \
    'divergences.append("source")' \
    'backups" / "source'
do
    if grep -q "$token" "$STATE_MANAGER"; then
        pass
    else
        fail "State manager lacks token: $token" \
             "Restore source snapshot/restore/divergence handling"
    fi
done

if grep -q 'rm -rf "$CANONICAL_SOURCE_DIR"' "$UNINSTALLER"; then
    fail "Uninstaller deletes restored canonical source" \
         "Let state manager own source restoration"
else
    pass
fi

# ── 17. Install-state canonical source path ────────────────────────────────────
header "Install-state canonical source path"

STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"
SOURCE_PATH_TEST="$SKILL_DIR/scripts/test-install-state-source-path.py"

if grep -q "HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2" "$STATE_MANAGER"; then
    pass
else
    fail "State manager lacks source-path shadowing fix marker" \
         "Restore snapshot source-path v2"
fi

if grep -q "gateway_file = gateway / relative" "$STATE_MANAGER"; then
    pass
else
    fail "Gateway loop lacks dedicated gateway_file variable" \
         "Do not reuse canonical source parameter"
fi

if grep -q "source = gateway / relative" "$STATE_MANAGER"; then
    fail "Canonical source parameter is still shadowed" \
         "Rename loop variable to gateway_file"
else
    pass
fi

if [[ -x "$SOURCE_PATH_TEST" ]] \
   && grep -q "INSTALL_STATE_SOURCE_PATH_REGRESSION_OK" "$SOURCE_PATH_TEST"; then
    pass
else
    fail "Source-path regression test is missing" \
         "Restore test-install-state-source-path.py"
fi


# ── 18. Git metadata and dirty working-tree preservation ───────────────────────
header "Git metadata and dirty working-tree preservation"

INSTALLER="$SKILL_DIR/scripts/install.sh"
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"
GIT_TEST="$SKILL_DIR/scripts/test-install-state-git-preservation.py"

for marker in \
    HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1 \
    HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1
do
    if grep -q "$marker" "$INSTALLER" \
       && grep -q "$marker" "$STATE_MANAGER"; then
        pass
    else
        fail "Missing Git preservation marker: $marker" \
             "Restore non-mutating Git transaction"
    fi
done

for forbidden in \
    'git add -A' \
    'git reset --hard' \
    'git config user\.'
do
    if grep -q "$forbidden" "$INSTALLER" \
       || grep -q "$forbidden" "$STATE_MANAGER"; then
        fail "Transaction still contains forbidden Git mutation: $forbidden" \
             "Use exact file snapshots without Git metadata mutation"
    else
        pass
    fi
done

if grep -q 'run_git(gateway, "reset"' "$STATE_MANAGER"; then
    fail "State manager still restores through git reset" \
         "Always restore byte snapshots"
else
    pass
fi

if [[ -x "$GIT_TEST" ]] \
   && grep -q "INSTALL_STATE_GIT_WORKTREE_PRESERVATION_OK" "$GIT_TEST"; then
    pass
else
    fail "Git preservation regression test is missing" \
         "Restore test-install-state-git-preservation.py"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
summary

if [[ $ERRORS -gt 0 ]]; then
    red "→ FAILED ($ERRORS error(s))"
    exit 2
elif [[ $WARNINGS -gt 0 ]]; then
    yellow "→ PASSED WITH WARNINGS ($WARNINGS warning(s))"
    exit 1
else
    green "→ ALL CHECKS PASSED"
    exit 0
fi