# ZFIN history rewrite kit

Temporary repo: the scripts for rewriting github.com/ZFIN/zfin as a linear history with old binaries in Git LFS
and LF line endings throughout, and the steps to run them on a fresh machine. It is deleted once the conversion is done (step 8).

The steps below rebuild the linear-history + LFS repo from a fresh clone of github.com/ZFIN/zfin and check it against
`expected/refs-pre-lfs.txt`: the trial build (2026-10-07 snapshot, pushed to the trial repo) before its LFS step.
The build is deterministic, so everything upstream hasn't changed since then comes out identical.

## What's in this repo

`scripts/pipeline_fp.sh` is the only script you run; it calls the others in this order.

| Script | What it does |
|---|---|
| `preflight.py` | Finds in a few seconds what would stop the build (a merge inside a carried branch or on a release's own line, a `release-*` branch not named `release-NNNN`) and lists what will be dropped (branches in `DROP`, tags other than `v*`/`archive/release-*`). `pipeline_fp.sh` runs it first; run it yourself with the GitHub clone to also see dropped refs. |
| `pipeline_fp.sh` | Runs the pre-flight check, then the whole rewrite in 5 steps (build, carry, LFS, verify, commit map) and writes logs and reports to the results directory. |
| `build_fp.py` | Step 1. Rebuilds main as a straight line from old main's first-parent commits, each with exactly its original files, author, dates and message. A merge becomes its PR's own commits when nothing else landed in between (fast-forwardable), one commit with the PR commit's message and author when the PR had one commit, and otherwise one commit that lists what it folded in; every commit on main has the files of a commit that really existed. Replays each `release-NNNN` on the commit it was cut from and tags it `archive/release-NNNN`. Edit `SKIP` to leave out a release. |
| `carry_refs.py` | Step 2. Re-applies each feature branch (all except `main`, `release-*` and the `DROP` list) onto the new history, and moves each `vNNNN` tag to the new commit with identical files. Edit `DROP` to leave out a branch. |
| `lfs_candidates.sh` | Step 3. Picks the blobs that go to Git LFS: old `.war`/`.jar`/`.jpi`/`.hpi` files, the old `home/zf_info/` site, and files of 1 MiB or more at paths main no longer has. Nothing in main's latest files is picked, so current main never uses LFS. |
| `lfs_convert.py` | Step 3. Uses git-filter-repo, on a standalone copy, to replace the picked blobs with LFS pointers (their contents go to `lfs/objects/`, and each affected commit gets a `.gitattributes` for its LFS paths) and to replace CRLF with LF in every other text file, in every commit (see "Line endings" below). |
| `verify_lfs.py` | Step 4. Checks every branch and tag path by path: each file must be unchanged, the same text with LF endings, or an LFS pointer that restores the original bytes; main must have no LFS pointers and no CRLF left; commit metadata must be identical. |
| `check_lfs_store.sh` | Step 4. Re-hashes every LFS object and checks that every pointer in history has its object. Also copied into the final repo, to check the NFS archive later. |
| `make_commit_map.py` | Step 5. Writes `zfin-commit-map.txt`: one line per old commit, `<old id> <new id> <kind>`, for finding old commits in the new history. |
| `compare_ref.py` | Not run by the pipeline. Compares one commit, branch or tag between the old and new repos, file by file, counting an LFS pointer as identical when it hashes to the original bytes, and CRLF -> LF files separately (step 6). |
| `compare_commits.py` | Not run by the pipeline; copied into the final repo next to the commit map. Looks up any old commits (or a random sample) in the commit map and compares each with its new commit, file by file, telling apart identical files, differences only in line endings or whitespace, and real differences (step 6, check D). |
| `remap-branch.sh` | Not run by the pipeline; copied into the final repo next to the commit map. Coworkers use it after the cutover to move a branch from their old clone onto the new history. |

`LFS-ARCHIVE.md` is the team's guide to the NFS copy of the LFS objects; the pipeline copies it into the final repo.
`expected/refs-pre-lfs.txt` holds the trial build's refs before its LFS step, for the comparison in step 5.

## 1. Tools

| Tool | macOS | Linux (Debian/Ubuntu) |
|---|---|---|
| git ≥ 2.36 | `brew install git` | `sudo apt install git` |
| python3 | included / `brew install python` | `sudo apt install python3` |
| git-filter-repo (2.47.0 used for `expected/`) | `brew install git-filter-repo` | `pip install --user git-filter-repo` |

Check: `git --version; python3 --version; git filter-repo --version`.
Disk: about 10 GB free (3 GB clone, 2 GB build input, 3.5 GB build).

## 2. Get the kit

    # where everything lives: an absolute path without spaces. Any parent directory works, but for the real
    # cutover use a persistent one (e.g. $HOME/zfin-cutover): /tmp can be emptied on reboot or after a few days.
    # Don't move it after the build: zfin.linear-fp.git reads zfin.source.git's objects by absolute path
    # (zfin.linear-fp-lfs.git, the result, is standalone and can go anywhere).
    WORK_DIR=/tmp/zfin-rewrite-test
    mkdir -p $WORK_DIR

    # this repo: README.md, LFS-ARCHIVE.md, scripts/ (11), expected/refs-pre-lfs.txt
    KIT_DIR=$WORK_DIR/zfin-rewrite-kit
    git clone https://github.com/rtaylorzfin/zfin-rewrite-kit.git $KIT_DIR

Keep `scripts/` and `LFS-ARCHIVE.md` side by side: `pipeline_fp.sh` reads `../LFS-ARCHIVE.md`.

## 3. Get the input: a fresh clone of GitHub

    # bare clone of ZFIN/zfin, about 3 GB (most of it is master's old history)
    MIRROR_REPO=$WORK_DIR/zfin.mirror.git
    git clone --bare git@github.com:ZFIN/zfin.git $MIRROR_REPO

## 4. Build

    cd $WORK_DIR

    # empty repo for the build input
    git init -q --bare zfin.source.git

    # all branches (main, release-1139 onward, feature branches) except master: the unrelated 1998-2021 CVS/SVN history
    git -C zfin.source.git fetch -q --no-tags $MIRROR_REPO 'refs/heads/*:refs/heads/*' '^refs/heads/master'

    # releases 1124-1138 exist only as archive/release-NNNN tags: fetch each as a release-NNNN branch
    git -C zfin.source.git fetch -q --no-tags $MIRROR_REPO 'refs/tags/archive/release-*:refs/heads/release-*'

    # the vNNNN tags of the GitHub Releases, v1175 onward (no other tags are kept)
    git -C zfin.source.git fetch -q --no-tags $MIRROR_REPO 'refs/tags/v*:refs/tags/v*'

    # make main the default branch
    git -C zfin.source.git symbolic-ref HEAD refs/heads/main

    # pre-flight check (seconds): STOP lines would make the build fail; DROP lines are left out, check they should be
    python3 -I $KIT_DIR/scripts/preflight.py zfin.source.git $MIRROR_REPO

    # build, carry branches + v tags, LFS, verify, store check, commit map (3-15 min)
    $KIT_DIR/scripts/pipeline_fp.sh zfin.source.git results zfin.linear-fp.git zfin.linear-fp-lfs.git

Fix every STOP before building: rebase the branch, or add it to `DROP` in `scripts/carry_refs.py` (the owner moves it
afterwards with `remap-branch.sh`). As of 2026-10-09 the check prints `ok` and one DROP line, for the tag
`main-before-tomcat10-upgrade` (dropped on purpose).

Expected along the way (as of 2026-10-29): step 3 converts 1485 blobs to LFS and gives about 1170 text blobs LF line endings;
the verify step ends ok; the store check prints `objects: 1485  corrupt: 0` and `pointers in history without an
object: 0`; the pack is about 61 MiB.

## 5. Compare with the trial build

    # refs of the trial build before its LFS step, and its main
    EXPECTED_REFS=$KIT_DIR/expected/refs-pre-lfs.txt
    TRIAL_MAIN=$(awk '$3=="refs/heads/main" {print $1}' $EXPECTED_REFS)

    # every ref except main should be identical
    diff <(git -C zfin.linear-fp.git for-each-ref | grep -v -e 'refs/source/' -e 'refs/heads/main$') \
         <(grep -v 'refs/heads/main$' $EXPECTED_REFS)

    # main should be the trial main plus the commits made upstream since
    git -C zfin.linear-fp.git merge-base --is-ancestor $TRIAL_MAIN main && echo "new main extends the trial main"
    git -C zfin.linear-fp.git rev-list --count $TRIAL_MAIN..main

Expected as of 2026-10-09 (upstream main @ d43e40c1e1):
- The first diff shows only `> ... refs/heads/ZFIN-10409-antibody-linkml`: that branch was merged (#2030) and deleted upstream.
- `new main extends the trial main`, and the count is 13 (more if main has moved since).
- A new `release-NNNN` branch, feature branch or `vNNNN` tag on GitHub shows up as an extra `<` line.

Why the comparison is before LFS: the LFS selection depends on main's tip (blobs not in it). Upstream main
changed `home/WEB-INF/lib/agr_curation_api.jar` back to an older version, so one jar version moved into LFS and
another out (still 1,466 objects). Every commit that holds either version gets a new id after the LFS step, so
the final refs differ from the trial's; that is expected.

## 6. Check any commit, branch or tag yourself

Every check below compares file contents byte for byte, apart from line endings: the LFS step also replaced CRLF with
LF (see "Line endings" below), and B, C and D say which files differ only in that. Pick any refs or commits you like;
four ways, from quickest to most direct.

**A. Tree ids, before the LFS step.** git names a commit's files by one hash over every path, mode and byte (the
tree id), so equal tree ids mean identical files. `zfin.linear-fp.git` can read the source's objects, so ask both:

    # a release: the old branch vs its new tag
    git -C $MIRROR_REPO rev-parse release-1160^{tree}
    git -C zfin.linear-fp.git rev-parse archive/release-1160^{tree}

    # a branch or v tag: same name on both sides
    git -C $MIRROR_REPO rev-parse v1183^{tree}
    git -C zfin.linear-fp.git rev-parse v1183^{tree}

    # any old commit: look up its new id in the build's map (old id, new id, kind), then compare
    OLD_COMMIT=005651b144
    NEW_COMMIT=$(awk -v c=$OLD_COMMIT 'index($1, c) == 1 {print $2; exit}' results/commit-map.txt)
    git -C $MIRROR_REPO rev-parse $OLD_COMMIT^{tree}
    git -C zfin.linear-fp.git rev-parse $NEW_COMMIT^{tree}

The map's kind says what to expect. Most commits are `fp`, `fp-from-ff-merge` or `release-NNNN`: same files. Two
kinds point at a different state on purpose: `side-folded-into-merge` (a commit from a PR branch that was folded
into its merge; the new commit has the merge's files) and `merge-single` (a PR's one commit, now carrying the merge's
files). For those, compare the merge commit itself instead.

**B. The final repo (what gets pushed), with `compare_ref.py`.** After the LFS step, old binaries are pointer files
and CRLF text files have LF endings, so tree ids differ wherever history holds either. `compare_ref.py` checks path by
path: a file passes if its bytes are the same, if it is an LFS pointer whose sha256 and size are the original file's,
or if it is the original text with each CRLF replaced by LF.

    python3 -I $KIT_DIR/scripts/compare_ref.py $MIRROR_REPO release-1160 zfin.linear-fp-lfs.git archive/release-1160

    # an old commit: the final ids are in results/zfin-commit-map.txt
    NEW_COMMIT=$(awk -v c=$OLD_COMMIT 'index($1, c) == 1 {print $2; exit}' results/zfin-commit-map.txt)
    python3 -I $KIT_DIR/scripts/compare_ref.py $MIRROR_REPO $OLD_COMMIT zfin.linear-fp-lfs.git $NEW_COMMIT

It prints e.g. `release-1160 -> archive/release-1160: 8939 files; 7615 identical, 1028 identical via LFS pointer,
296 identical apart from CRLF -> LF, 0 different` and exits 1 if anything differs.

**C. Check out both and diff the folders.** The most direct check; needs git-lfs (`git lfs install` once) and about
7 GB of disk (a full clone of each side).

    # the old release, from the clone
    git clone -q $MIRROR_REPO old-checkout
    git -C old-checkout checkout -q release-1160

    # the new release, with its LFS files restored from the final repo's lfs/objects
    git clone -q zfin.linear-fp-lfs.git new-checkout
    git -C new-checkout config lfs.url file://$WORK_DIR/zfin.linear-fp-lfs.git
    git -C new-checkout checkout -q archive/release-1160

    # no output means identical apart from line endings (.gitattributes is the LFS step's list of LFS paths);
    # drop --strip-trailing-cr to see the files whose CRLF became LF
    diff -r --strip-trailing-cr -x .git -x .gitattributes old-checkout new-checkout && echo identical

**D. Any old commits, through the commit map, ignoring whitespace.** For anyone who wants to see for themselves that
the rewrite kept their work: name old commits (abbreviated ids are fine) or ask for a random sample, and
`compare_commits.py` looks each one up in the map and compares it with its new commit. A file passes when its bytes
are the same or it is an LFS pointer to the old bytes; otherwise it is classed as differing only in line endings
(CRLF vs LF), only in whitespace, or in content. Only content differences (and missing, extra or mode-changed files)
fail the check.

    # here: the clone and the final repo, with the build's map
    python3 -I $KIT_DIR/scripts/compare_commits.py results/zfin-commit-map.txt $MIRROR_REPO zfin.linear-fp-lfs.git 005651b144 4a34ef0733
    python3 -I $KIT_DIR/scripts/compare_commits.py results/zfin-commit-map.txt $MIRROR_REPO zfin.linear-fp-lfs.git --sample 50

    # after the cutover, in your own old clone: fetch the new history next to the old one, then pass the clone twice
    git fetch https://github.com/ZFIN/zfin.git 'refs/heads/main:refs/remotes/rewritten/main'
    python3 -I compare_commits.py zfin-commit-map.txt . . <old commit> ...

Each commit gets one line, e.g. `4a34ef0733 -> 1d21f45d9e [fp] ok: 9051 files; 8757 identical, 0 via LFS pointer,
294 line endings only, 0 whitespace only, 0 different`; add `--list` to name the files behind the line-ending and
whitespace counts. The run exits 1 if any commit has a real difference. Commits of kind `side-folded-into-merge` and
`merge-single` carry their merge's files on purpose (see A), so their differences are reported but don't fail the
run; commits mapped to `-` were dropped as empty and are skipped.

## Line endings

About 290 files in main (Java, JSP, SQL, CSV, XML, ...) have CRLF line endings, and some files flipped between CRLF
and LF over the years. Each flip made `git blame` credit every line of the file to whichever commit flipped it
(e.g. #1295, the tomcat10 merge, for 1,733 lines of `HibernateExpressionRepository.java`), so the files were never
fixed in place. The LFS step fixes them in history instead: in every commit, each text file's CRLF becomes LF.
A few files (4 Java files, `term_stopwords.txt`, some old load CSVs) end their lines in CR alone, the classic-Mac
format, which git treats as binary and as one long line; their CRs become LF too.
Then no commit changes line endings, and blame credits each line to the commit that really wrote it.

- Text means no NUL byte and at most 1 non-printable byte per 128 printable ones (git's own test). Binary files are untouched, and so are files
  moved to LFS (they keep their original bytes). A lone CR inside a file whose lines end in LF is data (e.g. an
  empty field in `1085/ghost/drclonedis`) and is left alone.
- Every commit is kept, even one that only changed line endings and is now empty, so the commit map stays one to one.
- Liquibase checksums don't change: 4.30's checksums for `loadData` CSVs, `sql`/`sqlFile` and XML changelogs all
  ignore line endings, so databases with these changesets applied validate as before.
- `gradlew.bat` gets LF too. Windows runs it fine; to check it out with CRLF anyway, add the `.gitattributes` below.
- After the cutover, add a `.gitattributes` to main (an ordinary pull request) so new CRLF files are converted on
  commit and nobody brings the problem back:

      * text=auto eol=lf
      *.bat text eol=crlf

- `remap-branch.sh` moves branches made on the old history across the change without conflicts: lines a coworker
  added to a CRLF file land with LF endings. A file the branch adds keeps its own endings (the `.gitattributes`
  above converts it on its next commit).

## Tags, GitHub Releases and Zenodo

ZFIN/zfin's GitHub Releases (v1175 onward) are archived by Zenodo, through a webhook subscribed only to `release`
events. Zenodo makes a new version for a `release` event with action `published`, `released` or `created` on a
non-draft release, and rejects a release id it has already received. At the cutover, move the `vNNNN` tags in
place, after the branches (step C4 below):

    git -C $FINAL_REPO push --force $ZFIN_URL 'refs/tags/v*:refs/tags/v*'

Never delete a tag, and never delete and recreate a GitHub Release. A simulation on a throwaway repo (2026-11-04)
with a webhook for all events showed:

- Force-pushing main and then the tags in place sends only `push` events. The releases keep their ids and
  publish dates and stay published; Zenodo sees nothing.
- Deleting a tag sends `delete` and `release unpublished`, and turns its release into a draft. Pushing the tag
  back sends only `push` and `create`: the release stays a draft, hidden from the Releases page.
  `gh release edit vNNNN --draft=false` republishes it, sending `published` with the same release id (the
  simulation didn't go that far).

After the push, check that every release is still published (`false` on each line):

    gh api repos/ZFIN/zfin/releases --jq '.[]|"\(.tag_name) \(.draft)"'

## Cutover: replace ZFIN/zfin

Steps 3-6 change nothing on GitHub. The cutover runs them once more on a fresh clone, pushes the result over
ZFIN/zfin and archives it; then each developer moves their unmerged work across ("Moving work from the old history"
below). Run it from a persistent `$WORK_DIR` (step 2), with git-lfs installed (`brew install git-lfs` /
`sudo apt install git-lfs`) and push rights to ZFIN/zfin. ZFIN/zfin has no branch or tag protection yet, so the force
pushes need no settings changed; C6 adds it once they are done.

**C1. Freeze.** Announce a window with no pushes or merges to ZFIN/zfin. Before it starts, everyone pushes the
branches they want carried: only branches on GitHub at the clone in C2 are carried (minus `DROP`). Anything else
is moved afterwards with `remap-branch.sh`.

**C2. Build.** Steps 3-6, with a clone made after the freeze started. Check the pre-flight's DROP lines. Keep
`$MIRROR_REPO` until the as-is archive of the old repo is confirmed: after C4 it is the full copy of what GitHub had.

**C3. Check that GitHub hasn't changed since the clone.**

    ZFIN_URL=git@github.com:ZFIN/zfin.git
    FINAL_REPO=$WORK_DIR/zfin.linear-fp-lfs.git

    # no output: every branch and tag on GitHub is as cloned. Any output means someone pushed: go back to C2
    diff <(git -C $MIRROR_REPO for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags | sort -k2) \
         <(git ls-remote --refs $ZFIN_URL | awk '$2 ~ "^refs/(heads|tags)/" {print $1, $2}' | sort -k2)

**C4. Push.** The LFS objects first, so no pointer on GitHub is ever without its object, then the branches and
archive tags, and the `vNNNN` tags last (see "Tags, GitHub Releases and Zenodo": moved in place, never deleted).

    # LFS objects (the bare repo has no git-lfs hook, so git push alone would not send them); safe to rerun
    git -C $FINAL_REPO lfs push --all $ZFIN_URL

    # main, the carried feature branches and the archive/release-NNNN tags
    git -C $FINAL_REPO push --force $ZFIN_URL 'refs/heads/*:refs/heads/*' 'refs/tags/archive/*:refs/tags/archive/*'

    # the vNNNN tags, then check every release is still published (false on each line)
    git -C $FINAL_REPO push --force $ZFIN_URL 'refs/tags/v*:refs/tags/v*'
    gh api --paginate repos/ZFIN/zfin/releases --jq '.[]|"\(.tag_name) \(.draft)"'

**C5. Check GitHub against the final repo.**

    # no '<' lines: every ref of the new repo is on GitHub as pushed.
    # '>' lines: refs the push didn't touch, still on the old history
    diff <(git -C $FINAL_REPO for-each-ref --format='%(objectname) %(refname)' | sort -k2) \
         <(git ls-remote --refs $ZFIN_URL | awk '$2 ~ "^refs/(heads|tags)/" {print $1, $2}' | sort -k2)

The `>` lines are `master`, the `release-NNNN` branches (now `archive/release-NNNN` tags), the `DROP` branches and
the tags other than `v*`/`archive/release-*`. Each keeps the old history reachable on GitHub and offers it as a base
for new work. Delete the ones the team doesn't want kept, after their owners have moved any work they still need
(next section; that works from an old clone even after the delete):

    git push $ZFIN_URL --delete refs/heads/<name>

Deleting a branch with an open pull request closes that pull request. Never delete a `vNNNN` tag (none is in this
list: they are all in the new repo).

**C6. Protect main and the release tags.** With the history replaced, nothing should force-push or delete `main`
again; a `git push --force` from an old clone would put the old history back. Nor should a `vNNNN` tag move or
disappear (see "Tags, GitHub Releases and Zenodo"), or an `archive/release-NNNN` tag change. Two rulesets, with no
bypass, so they hold for admins too (admin rights needed to add them):

    # main: no force pushes, no deletion (ordinary pushes and merged pull requests still work)
    gh api -X POST repos/ZFIN/zfin/rulesets --input - <<'JSON'
    {"name": "main: no force push or delete", "target": "branch", "enforcement": "active",
     "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
     "rules": [{"type": "non_fast_forward"}, {"type": "deletion"}]}
    JSON

    # vNNNN and archive/release-NNNN tags: no moving, no deletion (creating new ones, e.g. by a new Release, still works)
    gh api -X POST repos/ZFIN/zfin/rulesets --input - <<'JSON'
    {"name": "release tags: no move or delete", "target": "tag", "enforcement": "active",
     "conditions": {"ref_name": {"include": ["refs/tags/v*", "refs/tags/archive/*"], "exclude": []}},
     "rules": [{"type": "update"}, {"type": "deletion"}]}
    JSON

    # check: both listed as active
    gh api repos/ZFIN/zfin/rulesets --jq '.[]|"\(.name) \(.target) \(.enforcement)"'

To change something later, set a ruleset's enforcement to disabled under Settings -> Rules -> Rulesets, and back to
active afterwards. Feature branches stay unprotected, so developers can still force-push them (next section).

**C7. Archive and announce.** Copy the final repo, which holds the LFS objects, the commit map, `remap-branch.sh`,
`compare_commits.py` and `LFS-ARCHIVE.md`, to the NFS archive, and check it there on a machine with the share mounted:

    rsync -a $FINAL_REPO/ cell:/research/zcentral/Vault/git/zfin.lfs.git/
    /research/zcentral/Vault/git/zfin.lfs.git/check_lfs_store.sh /research/zcentral/Vault/git/zfin.lfs.git --pointers

Then end the freeze, point everyone to the next section, and open the `.gitattributes` pull request (see
"Line endings").

### Moving work from the old history (developers)

Every commit id changed, so a branch in a clone made before the cutover is still based on the old history.
Never `git pull` or `git merge` between the two: they share only their first commit, so a merge drags the whole old
history (and its CRLF files) back in, and the pull request would show thousands of commits.

No local work that wasn't on GitHub at the cutover? Nothing to move: your pushed branches were carried and are on
GitHub already. Clone afresh, or do step 6 below in your old clone.

Otherwise, work in your old clone (it has the old commits the script needs; a fresh clone doesn't):

    # 1. the map and the script, from the NFS archive
    scp cell:/research/zcentral/Vault/git/zfin.lfs.git/{zfin-commit-map.txt,remap-branch.sh} ~/
    MAP=~/zfin-commit-map.txt

    # 2. fetch the new history; --force because the vNNNN and archive/release-NNNN tags moved,
    #    and git won't move an existing tag without it
    git fetch --force --tags origin

    # 3. for each branch with your work: was it carried as is?
    BR=my-branch
    grep "^$(git rev-parse $BR) " $MAP

What step 3 prints decides step 4:

- A line ending in `branch-$BR` (or `branch-$BR-exact-trees`): GitHub had exactly this branch, and it was carried.
  Take the carried version:

      git update-ref refs/pre-rewrite/$BR $BR
      git checkout $BR && git reset --hard origin/$BR

- A line of any other kind (`fp`, `release-NNNN`, ...): the branch has no commits of its own; it is already in main
  or a release. Delete it, and branch new work from `origin/main`.
- Nothing: the branch has commits GitHub didn't have at the cutover (unpushed commits, a `DROP` branch, a branch
  made after the freeze). Move it:

      # 4. rebase the branch's own commits onto the new history; saves the old branch as refs/pre-rewrite/$BR
      bash ~/remap-branch.sh $MAP $BR

  It rebases with `-X renormalize`, so edits to files whose CRLF became LF don't conflict, and ends with `ok` when
  the branch's changes are the same as before, apart from line endings. If it stops on a conflict, resolve it and
  `git rebase --continue`, or `git rebase --abort`. If it says the branch started from release commits and the
  pull request goes to main, run `git rebase origin/main` next. If the branch was carried and you only had extra
  commits on top, the result holds the carried commits plus yours; if `git log $BR..origin/$BR` shows commits,
  someone pushed to the carried branch since: `git rebase origin/$BR` before pushing.

Then, for either of the first and third cases:

    # 5. check: only your own commits. Thousands of lines mean the branch is still on the old history; don't push
    git log --oneline origin/main..$BR

    # push (updates an open pull request for $BR), or open a new one
    git push --force-with-lease origin $BR
    gh pr create --repo ZFIN/zfin --base main --head $BR

Undo either move with `git checkout $BR && git reset --hard refs/pre-rewrite/$BR`. Once every branch is moved:

    # 6. your main: reset it onto the new main (don't pull), and drop remote-tracking refs GitHub no longer has
    git checkout main && git reset --hard origin/main
    git fetch --prune origin

## 7. Clean up

    rm -rf $WORK_DIR

Before the cutover, nothing is written outside `$WORK_DIR`, and nothing is pushed anywhere. After the cutover, clean
up only once the NFS archive is checked (C7) and the old repo is archived as is.

## 8. When the conversion is done: delete this repo

Once ZFIN/zfin has been replaced with the rewritten history (the cutover), this kit is no longer needed. Deleting it is
tracked in ZFIN-10584 (due 2027-01-04); before deleting, attach a zip of the final kit to ZFIN-10473. The
scripts stay in the analysis folder and the commit map and `remap-branch.sh` in the NFS archive.

    # deleting needs the delete_repo scope (one time)
    gh auth refresh -h github.com -s delete_repo

    # delete the kit repo
    gh repo delete rtaylorzfin/zfin-rewrite-kit --yes
