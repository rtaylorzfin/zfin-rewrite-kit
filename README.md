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

## 7. Clean up

    rm -rf $WORK_DIR

Nothing is written outside `$WORK_DIR`, and nothing is pushed anywhere.

## 8. When the conversion is done: delete this repo

Once ZFIN/zfin has been replaced with the rewritten history (the cutover), this kit is no longer needed. Deleting it is
tracked in ZFIN-10584 (due 2027-01-04); before deleting, attach a zip of the final kit to ZFIN-10473. The
scripts stay in the analysis folder and the commit map and `remap-branch.sh` in the NFS archive.

    # deleting needs the delete_repo scope (one time)
    gh auth refresh -h github.com -s delete_repo

    # delete the kit repo
    gh repo delete rtaylorzfin/zfin-rewrite-kit --yes
