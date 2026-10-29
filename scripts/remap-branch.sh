#!/bin/bash
# remap-branch.sh: move a branch made on the OLD (pre-rewrite) ZFIN history onto the NEW history.
#
# Usage, in a clone that has your branch and the new history fetched (e.g. after `git fetch origin`):
#     remap-branch.sh <zfin-commit-map.txt> <branch> [<new-main-ref>]      (default new main: origin/main)
#
# What it does:
#   1. Finds where <branch> left the old history: its merge-base with the old main or with an old
#      release-NNNN tip (whichever leaves the fewest commits on the branch). The old tips are listed in
#      the map's header, so this works even after origin/main has moved to the new history.
#   2. Looks that commit up in the map (old -> new).
#   3. Saves the branch as refs/pre-rewrite/<branch>, then runs
#          git -c core.autocrlf=input rebase -X renormalize --onto <new base> <old base> <branch>
#      The new history has LF line endings where the old had CRLF; renormalize merges the branch's edits to
#      such files without conflicts, and autocrlf=input gives the lines it added LF too. (A file the branch
#      adds keeps its own endings.)
#      Only the branch's own commits are replayed. Merge commits (e.g. "merge main into my branch") are
#      dropped and their branch-side changes linearized, as plain `git rebase` does.
#   4. Checks that the branch's changes against its base are unchanged, apart from CRLF -> LF.
# Undo: git checkout <branch> && git reset --hard refs/pre-rewrite/<branch>
set -euo pipefail
MAP=${1:?usage: remap-branch.sh <zfin-commit-map.txt> <branch> [<new-main-ref>]}; BR=${2:?branch name}; NEWMAIN=${3:-origin/main}
die() { echo "remap-branch: $*" >&2; exit 1; }
[ -f "$MAP" ] || die "no map file $MAP"
git rev-parse -q --verify "refs/heads/$BR" >/dev/null || die "no local branch '$BR' (git checkout $BR first if it only exists on a remote)"
git rev-parse -q --verify "$NEWMAIN^{commit}" >/dev/null || die "'$NEWMAIN' not found; fetch the new history first"
[ -z "$(git -c filter.lfs.process= -c filter.lfs.smudge=cat -c filter.lfs.clean=cat -c filter.lfs.required=false status --porcelain --untracked-files=no)" ] || die "uncommitted changes; commit or stash them first"
for d in rebase-merge rebase-apply; do [ -e "$(git rev-parse --git-path $d)" ] && die "a rebase is already in progress; finish it (git rebase --continue) or abort it (git rebase --abort)"; done
grep -q "^# old-main " "$MAP" || die "$MAP has no '# old-main' header; is it the ZFIN commit map?"
# old and new history share only their first commit (identical in both), so sharing more means already moved
shared=$(git merge-base "$BR" "$NEWMAIN" 2>/dev/null || true)
[ -n "$shared" ] && [ "$(git rev-list --count "$shared")" -gt 1 ] && die "'$BR' is already on the new history"

# 1. old base: the merge-base with an old tip that leaves the fewest commits on the branch
best=; bestn=
while read -r _ name tip; do
    git cat-file -e "$tip^{commit}" 2>/dev/null || continue        # this clone never had that tip
    mb=$(git merge-base "$BR" "$tip" 2>/dev/null) || continue
    n=$(git rev-list --count "$mb..$BR")
    if [ -z "$bestn" ] || [ "$n" -lt "$bestn" ]; then best=$mb; bestn=$n; bestname=${name#old-}; fi
done < <(grep '^# old-' "$MAP")
[ -n "$best" ] || die "'$BR' shares no history with the old main or any old release branch"

# 2. map it; a commit that was dropped as empty (or not listed) is replaced by its nearest mapped ancestor
lookup() { awk -v c="$1" '$1==c {print $2; exit}' "$MAP"; }
old=$best; new=$(lookup "$old"); walked=0
while [ -z "$new" ] || [ "$new" = "-" ]; do
    old=$(git rev-parse -q --verify "$old^" 2>/dev/null) || die "no mapped ancestor for $best"
    new=$(lookup "$old"); walked=$((walked+1))
done
git cat-file -e "$new^{commit}" 2>/dev/null || die "mapped commit $new is not in this clone; fetch the new history (git fetch origin --tags)"
echo "branch '$BR': $bestn commit(s) on top of $bestname at ${best:0:10}"
[ $walked -gt 0 ] && echo "  note: ${best:0:10} has no entry of its own; using its ancestor ${old:0:10} ($walked step(s) up)"
echo "  old base ${old:0:10}  ->  new base ${new:0:10}"
if ! git merge-base --is-ancestor "$new" "$NEWMAIN"; then
    tag=$(git tag --points-at "$new" 'archive/release-*' | head -1)
    echo "  note: the branch started from release commits, so it lands next to ${tag:-a release tag}, just off main."
    echo "        If it is meant for main, run 'git rebase $NEWMAIN' afterwards."
fi

# 3. back up and rebase
git update-ref "refs/pre-rewrite/$BR" "$BR"
echo "  saved the old branch as refs/pre-rewrite/$BR"
# Old commits in the new history store some files in Git LFS. The rebase never needs their contents, so the
# LFS filter is switched off for it: no downloads (and no failure without git-lfs); LFS files stay pointers.
NOLFS=(-c filter.lfs.process= -c filter.lfs.smudge=cat -c filter.lfs.clean=cat -c filter.lfs.required=false)
if ! git "${NOLFS[@]}" -c core.autocrlf=input rebase -X renormalize --onto "$new" "$old" "$BR"; then
    echo
    echo "The rebase stopped on a conflict. Resolve it and run 'git rebase --continue',"
    echo "or give up with 'git rebase --abort' (the branch is then unchanged)."
    exit 2
fi

# 4. same changes as before? (CRs removed first: the new history has LF where the old had CRLF)
if [ "$(git diff "$old" "refs/pre-rewrite/$BR" | tr -d '\r' | git patch-id --stable | cut -d' ' -f1)" = \
     "$(git diff "$new" "$BR" | tr -d '\r' | git patch-id --stable | cut -d' ' -f1)" ]; then
    echo "ok: '$BR' is now on the new history with the same changes against its base (line endings aside)"
else
    echo "done: '$BR' is now on the new history. Its diff against the base differs from before (expected only if"
    echo "      you resolved conflicts, or the branch started inside an old PR branch that was merged). Review with:"
    echo "      git diff $new $BR"
fi
echo "Next: git push --force-with-lease <your remote> $BR    (updates an open pull request)"
