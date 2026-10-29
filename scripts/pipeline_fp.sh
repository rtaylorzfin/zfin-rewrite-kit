#!/bin/bash
# First-parent rewrite, end to end: build, carry branches + v tags, LFS + line endings, verify, commit map.
# Usage: scripts/pipeline_fp.sh <source.git> <results-dir> <build.git> <final-lfs.git>
#
# <source.git>    bare repo with refs/heads/main, refs/heads/release-* (1124-1138 made from the archive/release-*
#                 tags), the feature branches and refs/tags/v*; no master (README step 4).
# <build.git>     created fresh (pre-LFS; alternates to the source objects).
# <final-lfs.git> created fresh: standalone mirror of the build with LFS applied = what gets pushed and archived.
# Needs git-filter-repo; git-lfs is not needed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$1" && pwd); OUT=$(mkdir -p "$2" && cd "$2" && pwd); BUILD=$3; FIN=$4
ts() { date '+%H:%M:%S'; }

echo "$(ts) 0/5 pre-flight check (stops here if the build would fail)"
python3 -I "$HERE/preflight.py" "$SRC" > "$OUT/preflight-output.txt" || { grep -E '^STOP|problem' "$OUT/preflight-output.txt"; exit 1; }
tail -1 "$OUT/preflight-output.txt"

echo "$(ts) 1/5 build (main = first-parent line, original trees; releases on their real cut)"
rm -rf "$BUILD"; git init -q --bare "$BUILD"; BUILD=$(cd "$BUILD" && pwd)
{ echo "$SRC/objects"; cat "$SRC/objects/info/alternates" 2>/dev/null || true; } > "$BUILD/objects/info/alternates"
(cd "$BUILD" && python3 -I "$HERE/build_fp.py" "$SRC" "$OUT") | tee "$OUT/build-output.txt"

echo "$(ts) 2/5 carry feature branches and v tags"
(cd "$BUILD" && python3 -I "$HERE/carry_refs.py" "$SRC" "$OUT/commit-map.txt" "$OUT/carry-commit-map.txt") > "$OUT/carry-output.txt" 2>&1
grep -E 'mode=|^v[0-9]' "$OUT/carry-output.txt" | grep -v DROPPED

echo "$(ts) 3/5 LFS + CRLF -> LF on a standalone copy"
rm -rf "$FIN"; git clone -q --mirror --no-local "$BUILD" "$FIN"; FIN=$(cd "$FIN" && pwd)
(cd "$FIN" && git for-each-ref --format='delete %(refname)' refs/source refs/remotes | git update-ref --stdin && git config --remove-section remote.origin
 git for-each-ref --format='%(refname) %(objectname)' > "$OUT/lfs-pre-refs.txt"
 "$HERE/lfs_candidates.sh" "$OUT/strip"
 python3 -I "$HERE/lfs_convert.py" "$OUT/strip/strip-blob-ids.txt" 2>&1 | tail -1)

echo "$(ts) 4/5 verify LFS + line endings + store"
(cd "$FIN" && python3 -I "$HERE/verify_lfs.py" "$BUILD" "$OUT/lfs-pre-refs.txt") > "$OUT/verify-lfs-output.txt" 2>&1 || { tail -5 "$OUT/verify-lfs-output.txt"; exit 1; }
tail -3 "$OUT/verify-lfs-output.txt"
"$HERE/check_lfs_store.sh" "$FIN" --pointers | tee "$OUT/check-lfs-store-output.txt"
git -C "$FIN" count-objects -vH | grep size-pack

echo "$(ts) 5/5 commit map + archive files"
python3 -I "$HERE/make_commit_map.py" "$SRC" "$BUILD" "$FIN" "$OUT/commit-map.txt" "$OUT/carry-commit-map.txt" "$OUT/zfin-commit-map.txt"
cp "$HERE/check_lfs_store.sh" "$HERE/remap-branch.sh" "$HERE/compare_commits.py" "$OUT/zfin-commit-map.txt" "$FIN/"
sed 's/__ARCHIVE_NAME__/zfin.lfs.git/g' "$HERE/../LFS-ARCHIVE.md" > "$FIN/LFS-ARCHIVE.md"
echo "$(ts) done: $FIN (reports and commit map in $OUT)"
