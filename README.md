# ZFIN history rewrite kit

Temporary repo: the scripts for rewriting github.com/ZFIN/zfin as a linear history with old binaries in Git LFS,
and the steps to run them on a fresh machine. It is deleted once the conversion is done (step 7).

The steps below rebuild the linear-history + LFS repo from a fresh clone of github.com/ZFIN/zfin and check it against
`expected/refs-pre-lfs.txt`: the trial build (2026-10-07 snapshot, pushed to the trial repo) before its LFS step.
The build is deterministic, so everything upstream hasn't changed since then comes out identical.

## 1. Tools

| Tool | macOS | Linux (Debian/Ubuntu) |
|---|---|---|
| git ≥ 2.36 | `brew install git` | `sudo apt install git` |
| python3 | included / `brew install python` | `sudo apt install python3` |
| git-filter-repo (2.47.0 used for `expected/`) | `brew install git-filter-repo` | `pip install --user git-filter-repo` |

Check: `git --version; python3 --version; git filter-repo --version`.
Disk: about 8 GB free (3+ GB clone, 3.5 GB build).

## 2. Get the kit

    # where everything lives: an absolute path without spaces. Any parent directory works, but for the real
    # cutover use a persistent one (e.g. $HOME/zfin-cutover): /tmp can be emptied on reboot or after a few days.
    # Don't move it after the build: zfin.source.git and zfin.linear-fp.git point at the clone by absolute path
    # (zfin.linear-fp-lfs.git, the result, is standalone and can go anywhere).
    WORK_DIR=/tmp/zfin-rewrite-test
    mkdir -p $WORK_DIR

    # this repo: README.md, LFS-ARCHIVE.md, scripts/ (9), expected/refs-pre-lfs.txt
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

    # read objects straight from the clone instead of copying them (the clone is not modified)
    echo "$MIRROR_REPO/objects" > zfin.source.git/objects/info/alternates

    # all branches: main, release-1139..1185, feature branches (and master, removed next)
    git -C zfin.source.git fetch -q --no-tags $MIRROR_REPO 'refs/heads/*:refs/heads/*'

    # drop master: the unrelated 1998-2021 CVS/SVN history
    git -C zfin.source.git update-ref -d refs/heads/master

    # releases 1124-1138 exist only as archive/release-NNNN tags: make a release-NNNN branch at each
    for tag in $(git -C $MIRROR_REPO for-each-ref --format='%(refname:short)' 'refs/tags/archive/release-*'); do
        git -C zfin.source.git update-ref refs/heads/${tag#archive/} $(git -C $MIRROR_REPO rev-parse $tag^{commit})
    done

    # the v1175..v1185 tags of the GitHub Releases (no other tags are kept)
    git -C zfin.source.git fetch -q --no-tags $MIRROR_REPO 'refs/tags/v*:refs/tags/v*'

    # make main the default branch
    git -C zfin.source.git symbolic-ref HEAD refs/heads/main

    # build, carry branches + v tags, LFS, verify, store check, commit map (3-15 min)
    $KIT_DIR/scripts/pipeline_fp.sh zfin.source.git results zfin.linear-fp.git zfin.linear-fp-lfs.git

Expected along the way: the verify step ends ok; the store check prints `objects: 1466  corrupt: 0` and
`pointers in history without an object: 0`; the pack is about 91 MiB. Ignore the final "Run test_lfs_clients.sh,
then archive" hint: the client test is not in the kit, and this test build is not archived.

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

## 6. Clean up

    rm -rf $WORK_DIR

Nothing is written outside `$WORK_DIR`, and nothing is pushed anywhere.

## 7. When the conversion is done: delete this repo

Once ZFIN/zfin has been replaced with the rewritten history (the cutover), this kit is no longer needed. The
scripts stay in the analysis folder and the commit map and `remap-branch.sh` in the NFS archive.

    # deleting needs the delete_repo scope (one time)
    gh auth refresh -h github.com -s delete_repo

    # delete the kit repo
    gh repo delete rtaylorzfin/zfin-rewrite-kit --yes
