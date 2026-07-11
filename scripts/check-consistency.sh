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