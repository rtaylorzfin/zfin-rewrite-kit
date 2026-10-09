#!/bin/bash
# Integrity check for an LFS store (e.g. the NFS archive): every object's file name is its sha256,
# so re-hash them all. Optionally also check that every LFS pointer in the repo's refs has an object.
# Usage: check_lfs_store.sh <bare repo with lfs/objects> [--pointers]
set -uo pipefail
R=$(cd "$1" && pwd); O="$R/lfs/objects"; bad=0; n=0
if command -v sha256sum >/dev/null; then SHA256=(sha256sum); else SHA256=(shasum -a 256); fi
[ -d "$O" ] || { echo "no $O"; exit 1; }
git -C "$R" rev-parse --is-bare-repository >/dev/null 2>&1 || echo "WARNING: $R is not a git repository; git-lfs will not accept it as lfs.url"
while IFS= read -r f; do
  n=$((n+1)); want=$(basename "$f"); got=$("${SHA256[@]}" "$f" | cut -c1-64)
  [ "$want" = "$got" ] || { echo "CORRUPT $f"; bad=$((bad+1)); }
done < <(find "$O" -type f)
echo "objects: $n  corrupt: $bad  size: $(du -sh "$O" | cut -f1)"
if [ "${2:-}" = "--pointers" ]; then
  missing=$(git -C "$R" rev-list --objects --all | awk 'NF>1{print $1}' \
    | git -C "$R" cat-file --batch-check='%(objectname) %(objecttype) %(objectsize)' | awk '$2=="blob" && $3<200{print $1}' \
    | git -C "$R" cat-file --batch 2>/dev/null | grep -a '^oid sha256:' | cut -d: -f2 | sort -u \
    | while read -r oid; do [ -f "$O/${oid:0:2}/${oid:2:2}/$oid" ] || echo "$oid"; done | wc -l | tr -d ' ')
  echo "pointers in history without an object: $missing"; [ "$missing" = 0 ] || bad=$((bad+1))
fi
[ $bad -eq 0 ] && echo ok || { echo FAIL; exit 1; }
