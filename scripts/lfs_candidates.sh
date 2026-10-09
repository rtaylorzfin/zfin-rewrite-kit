#!/bin/bash
# List the historical blobs to move to LFS. Nothing in main's tip tree is ever selected, so current
# main never involves LFS. A blob is selected if it is NOT in main's tip and any of:
#   1. binary artifact: path ends in .war/.jar/.jpi/.hpi                       (app jars, Jenkins)
#   2. path under home/zf_info/   (old static site: atlas images, photos, PDFs; removed from main
#                                  2026-07-31 by ZFIN-10382, still in releases 1139-1183)
#   3. raw size >= 1 MiB and its path no longer exists in main's tip           (deleted data files:
#      Sanger .fa, .ser test fixtures, liquibase .tar, old .json dumps, ...). Old versions of files
#      main still has are never selected, so history/blame of current files stays in git.
# Paths come from `git rev-list --objects` (one name per blob: the first one seen).
#
# Usage (cwd = the FINAL built repo, after carry_refs.py; refs/source/* are ignored): lfs_candidates.sh <out-dir>
# Do not run it on the source repo: release-1123 has the dropped master history as ancestors.
#   writes candidates.txt ("<blob> <size> <rule> <path>"), keep-tip-blobs.txt, strip-blob-ids.txt
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
git ls-tree -r main | awk '{print $3}' | sort -u > "$OUT/keep-tip-blobs.txt"
git ls-tree -r --name-only main > "$OUT/.tippaths"
git rev-list --objects main $(git for-each-ref --format='%(refname)' refs/heads/ refs/tags/) \
  | awk 'NF>1 { p=$2; for (i=3;i<=NF;i++) p=p" "$i; print $1"\t"p }' | sort -t$'\t' -k1,1 -u > "$OUT/.objs"
cut -f1 "$OUT/.objs" | git cat-file --batch-check=$'%(objectname)\t%(objecttype)\t%(objectsize)' \
  | awk -F'\t' '$2=="blob"{print $1"\t"$3}' | join -t$'\t' - "$OUT/.objs" \
  | awk -F'\t' 'FILENAME==ARGV[1] {tip[$0]=1; next} FILENAME==ARGV[2] {tipp[$0]=1; next}
      ($1 in tip) {next}
      tolower($3) ~ /\.(war|jar|jpi|hpi)$/          {print $1"\t"$2"\tbinary\t"$3; next}
      $3 ~ /^home\/zf_info\//                      {print $1"\t"$2"\tzf_info\t"$3; next}
      $2 >= 1048576 && !($3 in tipp)               {print $1"\t"$2"\tdeleted-large\t"$3; next}' \
      "$OUT/keep-tip-blobs.txt" "$OUT/.tippaths" - > "$OUT/candidates.txt"
cut -f1 "$OUT/candidates.txt" | sort -u > "$OUT/strip-blob-ids.txt"
rm -f "$OUT/.objs" "$OUT/.tippaths"
awk -F'\t' '{n[$3]++; s[$3]+=$2; N++; S+=$2} END{for (k in n) printf "  %-14s %5d blobs %7.0f MB\n", k, n[k], s[k]/1048576; printf "  %-14s %5d blobs %7.0f MB  -> strip-blob-ids.txt\n", "total", N, S/1048576}' "$OUT/candidates.txt"
