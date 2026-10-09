# ZFIN Git LFS archive

The rewritten `github.com/ZFIN/zfin` history keeps old binaries and large retired files in Git LFS:
- old jars and Jenkins plugins
- the old `home/zf_info` static site
- large data files that were later deleted

Current `main` never uses LFS. The LFS files appear only when you check out an old release tag
(`archive/release-NNNN`) or an old commit.

GitHub hosts these files, but ZFIN is on the free plan, which includes 10 GiB of LFS storage and
10 GiB of download bandwidth per month. A complete copy lives on NFS as a fallback:

    cell:/research/zcentral/Vault/git/__ARCHIVE_NAME__

That directory is a bare git repository: the full rewritten history, plus every LFS object under
`lfs/objects/<aa>/<bb>/<sha256>`. Copy this README into it when archiving.

## When you need it

Checking out an old tag fails with a message like:

    Error downloading object: docker/tomcat/postgresql-42.2.18.jar (0c89197): Smudge error: ...

This happens when GitHub's LFS quota is used up for the month, or when the objects are missing on GitHub.

First clean up the half-finished checkout:

    git checkout -f main && git clean -fd     # check `git clean -nd` first if you keep untracked files

## Option A: a machine with the NFS share mounted

Point git-lfs at the archive for this clone. Your git remote stays GitHub.

    git config lfs.url file:///research/zcentral/Vault/git/__ARCHIVE_NAME__
    git checkout archive/release-1160          # real jars, byte-identical to what was deployed

    git config --unset lfs.url                 # optional: go back to GitHub's LFS later

## Option B: no NFS mount (laptop, remote)

Copy the archive once (about 2.7 GB), then point at the copy:

    rsync -a cell:/research/zcentral/Vault/git/__ARCHIVE_NAME__/ ~/zfin-lfs.git/
    git config lfs.url file://$HOME/zfin-lfs.git

The copy must stay a git repository. A folder holding only `lfs/objects` does not work; `git init --bare` plus the
`lfs/objects` folder is enough.

## Option C: restore GitHub's copy (maintainers)

If objects are missing on GitHub, re-upload everything from the archive:

    cd /research/zcentral/Vault/git/__ARCHIVE_NAME__
    git lfs push --all git@github.com:ZFIN/zfin.git

## Checking the archive

Each object's file name is its SHA-256, so the archive can verify itself:

    check_lfs_store.sh /research/zcentral/Vault/git/__ARCHIVE_NAME__ --pointers

A copy of the script sits next to this file (also in `git-vault/analysis-2026-10-07/scripts/`). It re-hashes every object and confirms that every LFS
pointer anywhere in history has its object.

## Commit map and remap-branch.sh

Every commit ID changed in the rewrite. Two files next to this one help with that:

- `zfin-commit-map.txt`: one line per old commit, `<old id> <new id> <kind>`. Find an old ID with
  `grep '^<old-id>' zfin-commit-map.txt`.
- `remap-branch.sh`: moves a branch made on the old history onto the new one. Run it in an old clone;
  its header and `COWORKER-GUIDE.md` explain how.

## You don't need git-lfs at all

Without git-lfs, old tags check out normally, and each LFS file shows up as a three-line text placeholder
(`version … / oid sha256:… / size …`). Install git-lfs (`brew install git-lfs`) only if you need the real
files from an old release.
