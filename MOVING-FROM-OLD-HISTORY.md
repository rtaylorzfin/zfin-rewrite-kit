# Moving work from the old history

ZFIN/zfin's history was rewritten: main is now a straight line with no merge commits, old binaries moved to Git LFS,
and every text file has LF line endings throughout its history. The files of every commit are the same, but every
commit id changed. A branch in a clone made before the rewrite is still based on the old history.

**Never `git pull` or `git merge` between the old and new history.** They share only their first commit, so a merge
drags the whole old history (and its CRLF files) back in, and the pull request would show thousands of commits.

## No local work that wasn't on GitHub at the cutover?

Nothing to move: the branches on GitHub at the cutover were carried over and are on GitHub already. Clone afresh,
or do step 6 below in your old clone.

## Otherwise: move each branch

Work in your old clone; it has the old commits the script needs (a fresh clone doesn't).

    # 1. the commit map and the script, from the NFS archive
    scp cell:/research/zcentral/Vault/git/zfin.lfs.git/{zfin-commit-map.txt,remap-branch.sh} ~/
    MAP=~/zfin-commit-map.txt

    # 2. fetch the new history; --force because the vNNNN and archive/release-NNNN tags moved,
    #    and git won't move an existing tag without it
    git fetch --force --tags origin

    # 3. for each branch with your work: was it carried as is?
    BR=my-branch
    grep "^$(git rev-parse $BR) " $MAP

What step 3 prints decides step 4:

- **A line ending in `branch-$BR` (or `branch-$BR-exact-trees`)**: GitHub had exactly this branch, and it was
  carried. Take the carried version:

      git update-ref refs/pre-rewrite/$BR $BR
      git checkout $BR && git reset --hard origin/$BR

- **A line of any other kind (`fp`, `release-NNNN`, ...)**: the branch has no commits of its own; it is already in
  main or a release. Delete it, and branch new work from `origin/main`.

- **Nothing**: the branch has commits GitHub didn't have at the cutover (unpushed commits, a branch that wasn't
  carried, a branch made after the freeze). Move it:

      # 4. rebase the branch's own commits onto the new history; saves the old branch as refs/pre-rewrite/$BR
      bash ~/remap-branch.sh $MAP $BR

  It rebases with `-X renormalize`, so edits to files whose CRLF became LF don't conflict, and ends with `ok` when
  the branch's changes are the same as before, apart from line endings. If it stops on a conflict, resolve it and
  `git rebase --continue`, or `git rebase --abort`. If it says the branch started from release commits and the pull
  request goes to main, run `git rebase origin/main` next. If the branch was carried and you only had extra commits
  on top, the result holds the carried commits plus yours; if `git log $BR..origin/$BR` shows commits, someone pushed
  to the carried branch since: `git rebase origin/$BR` before pushing.

Then, for either the first or the third case:

    # 5. check: only your own commits. Thousands of lines mean the branch is still on the old history; don't push
    git log --oneline origin/main..$BR

    # push (updates an open pull request for $BR), or open a new one
    git push --force-with-lease origin $BR
    gh pr create --repo ZFIN/zfin --base main --head $BR

Undo either move with `git checkout $BR && git reset --hard refs/pre-rewrite/$BR`.

## Once every branch is moved

    # 6. your main: reset it onto the new main (don't pull), and drop remote-tracking refs GitHub no longer has
    git checkout main && git reset --hard origin/main
    git fetch --prune origin

## Finding an old commit

`zfin-commit-map.txt` has one line per old commit: `<old id> <new id> <kind>`. To find where an old commit went:

    grep "^<old id>" $MAP

Most kinds (`fp`, `fp-from-ff-merge`, `release-NNNN`) mean the new commit has exactly the old commit's files.
`side-folded-into-merge` and `merge-single` point at the commit that now holds the change: a pull request's commits
were combined into one, with the files of its merge.
