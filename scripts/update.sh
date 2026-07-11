#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_SRC="${HERMES_GATEWAY_SRC:-/opt/hermes}"

# === Shared functions (adapted from install.sh) ===

detect_version() {
    cd "$GATEWAY_SRC"
    if git describe --tags 2>/dev/null; then return; fi
    if [ -f VERSION ]; then cat VERSION; return; fi
    echo "unknown"
}

find_patch_dir() {
    local ver="$1"
    local candidates=(
        "$SKILL_DIR/patches/$ver"
        "$SKILL_DIR/patches/v${ver#v}"
    )
    for d in "${candidates[@]}"; do
        if [ -f "$d/series" ]; then
            echo "$d"
            return
        fi
    done
    # fallback: patches/ (flat layout)
    if ls "$SKILL_DIR/patches/"*.patch >/dev/null 2>&1; then
        echo "$SKILL_DIR/patches"
        return
    fi
    echo ""
}

apply_patches() {
    local patch_dir="$1"
    cd "$GATEWAY_SRC"
    if [ -f "$patch_dir/series" ]; then
        while read -r patch_id; do
            [ -z "$patch_id" ] && continue
            local patch_file="$patch_dir/${patch_id}-*.patch"
            if ! ls $patch_file >/dev/null 2>&1; then
                echo "[FAIL] Patch $patch_id not found"
                exit 1
            fi
            for f in $patch_file; do
                if git apply --check "$f" 2>/dev/null; then
                    git apply "$f"
                    echo "[OK] Applied $patch_id"
                else
                    echo "[FAIL] Cannot apply $patch_id (version mismatch?)"
                    exit 1
                fi
            done
        done < "$patch_dir/series"
    else
        # Flat layout: apply in correct dependency order
        local ORDERED=(002 003 004 005 001)
        for patch_id in "${ORDERED[@]}"; do
            local matched=()
            for f in "$patch_dir"/${patch_id}-*.patch; do
                [ -f "$f" ] && matched+=("$f")
            done
            if [ ${#matched[@]} -eq 0 ]; then
                echo "[WARN] No patch found for $patch_id"
                continue
            fi
            for f in "${matched[@]}"; do
                local name="$(basename "$f")"
                if git apply --check "$f" 2>/dev/null; then
                    git apply "$f"
                    echo "[OK] Applied $name"
                else
                    echo "[FAIL] Cannot apply $name"
                    exit 1
                fi
            done
        done
    fi
    git add -A
    git commit -m "hermes-wechat-enhance installed (version: $(detect_version))"
    echo "[OK] All patches applied"
}

# === Main update logic ===

main() {
    echo "=== Hermes WeChat Enhance Updater ===="

    # 1. cd to gateway source
    if [ ! -d "$GATEWAY_SRC" ]; then
        echo "[FAIL] Gateway source not found: $GATEWAY_SRC"
        echo "Set HERMES_GATEWAY_SRC to the correct path."
        exit 1
    fi
    cd "$GATEWAY_SRC"
    echo "[OK] Working in $GATEWAY_SRC"

    # 2. git stash — save user's manual changes
    local STASH_NEEDED=false
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        echo "Stashing user modifications..."
        git stash push -m "hermes-wechat-enhance-update-auto-stash" || true
        STASH_NEEDED=true
        echo "[OK] User changes stashed"
    else
        echo "[SKIP] No uncommitted user changes to stash"
    fi

    # 3. git checkout pristine — restore to original state
    if git rev-parse --verify pristine 2>/dev/null; then
        echo "Checking out pristine commit..."
        git checkout pristine
        echo "[OK] Restored to pristine commit"
    else
        echo "[WARN] No 'pristine' ref found. Using HEAD as baseline."
        # Create a pristine ref from current HEAD so we can track it
        git branch -f pristine HEAD 2>/dev/null || true
    fi

    # 4. Run install.sh's apply logic: version detection → find patch → apply
    echo ""
    echo -n "Detecting Hermes version... "
    local VERSION
    VERSION="$(detect_version)"
    echo "$VERSION"

    echo -n "Finding patch set... "
    local PATCH_DIR
    PATCH_DIR="$(find_patch_dir "$VERSION")"
    if [ -z "$PATCH_DIR" ]; then
        echo "[FAIL] No matching patch set for version $VERSION"
        echo "Available: $(ls -d "$SKILL_DIR/patches/"*/ 2>/dev/null || echo 'flat layout')"
        # Restore stash before exiting
        if [ "$STASH_NEEDED" = true ]; then
            cd "$GATEWAY_SRC"
            git stash pop 2>/dev/null || true
        fi
        exit 1
    fi
    echo "$PATCH_DIR"

    echo "Applying patches..."
    apply_patches "$PATCH_DIR"

    # 5. git stash pop — restore user's changes
    if [ "$STASH_NEEDED" = true ]; then
        cd "$GATEWAY_SRC"
        echo "Restoring user changes..."
        if git stash pop 2>/dev/null; then
            echo "[OK] User changes restored on top of updated patches"
        else
            echo "[WARN] Could not auto-pop stash (conflicts). Manual resolution needed."
            echo "       Your changes are saved in 'stash@{0}'."
            echo "       Run: cd $GATEWAY_SRC && git stash pop"
        fi
    fi

    echo ""
    echo "=== Update complete ==="
    echo "Restart Hermes gateway to apply changes."
}

main "$@"