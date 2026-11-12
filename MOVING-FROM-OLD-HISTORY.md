# Moving work from the old history

ZFIN/zfin's history was rewritten: main is now a straight line with no merge commits, old binaries moved to Git LFS,
and every text file has LF line endings throughout its history. The files of every commit are the same, but every
commit id changed. A branch in a clone made before the rewrite is still based on the old history.

**Never `git pull` or `git merge` between the old and new history.** They share only their first commit, so a merge
drags the whole old history (and its CRLF files) back in, and the pull request would show thousands of commits.

## No local work that wasn't on GitHub at the cutover?

Nothing to move: the branches on GitHub at the cutover were carried over and are on GitHub already. Clone afresh
and use them from there.

## Copy your commits into a fresh clone, as patches

Save your commits as patch files in your old clone, make a fresh clone of the new history, and apply them there.
Below, the old clone's branch and the new clone's branch have different names, so it is clear which is which; once
you are done, the old clone is no longer needed.

    OLD_CLONE=~/zfin                # your clone from before the cutover
    OLD_BR=my-work                  # the branch in it with your commits
    NEW_BR=my-work-moved            # the name for the branch in the new clone (any name)

    # 1. in the old clone: check the commits are only your own, then save them as patch files
    #    (thousands of lines? see "If step 1 lists thousands of commits" below)
    cd $OLD_CLONE
    git log --oneline origin/main..$OLD_BR
    git format-patch origin/main..$OLD_BR -o ~/zfin-patches

    # 2. a fresh clone of the new history, and a new branch on its main
    git clone git@github.com:ZFIN/zfin.git ~/zfin-new
    cd ~/zfin-new
    git switch -c $NEW_BR origin/main

    # 3. apply the patches, oldest first; each becomes a commit with your message, author and date
    git am --no-keep-cr ~/zfin-patches/*.patch

Many files that had CRLF line endings in the old history have LF in the new one, so your patches to them have CRLF
lines. `git am` removes the CR at the end of each patch line before applying (`--no-keep-cr` makes sure, even if
`am.keepcr` is set in your git config), so they apply to the LF files, and files your commits add get LF endings
too. Use `git am`, not `git apply`: `git apply` keeps the CRs, and those patches fail. Binary files apply unchanged.
`format-patch` leaves out merge commits (for example "merge main into my branch"); the changes they brought in are
already on the new main.

If a patch doesn't apply (a change made on main since your branch started), `git am` stops. Apply what fits with
`git apply --reject --whitespace=nowarn $(git rev-parse --git-path rebase-apply/patch)`, fix the parts left in the
`.rej` files by hand, `git add` the files, and `git am --continue`. Or start over with `git am --abort`.

    # 4. check: only your own commits, then push and open a pull request
    git log --oneline origin/main..$NEW_BR
    git push -u origin $NEW_BR
    gh pr create --repo ZFIN/zfin --base main --head $NEW_BR

    # 5. once every branch is moved
    rm -r ~/zfin-patches

Undo: `git switch main && git branch -D $NEW_BR`, then start again at step 3 (`git switch -c $NEW_BR origin/main`
first). The old clone is never changed.

**If step 1 lists thousands of commits**, the old clone's `origin/main` has already been updated to the new history
(someone ran `git fetch` in it after the cutover). Use the old clone's own `main` instead of `origin/main`, if that
is still on the old history, or name your commits: `git format-patch <oldest id>^..<newest id>`.

**If the branch was on GitHub at the cutover, with more commits on top in your old clone**, it was carried: start
from it (`git switch -c $NEW_BR origin/<branch>` in step 2) and make patches of only the commits it doesn't have, by
naming them as above. Push to the carried branch's name to update its pull request.

**Without patch files:** fetch the commits straight from the old clone and cherry-pick them. Same result, with
`-X renormalize` and `core.autocrlf=input` handling the line endings. In step 2's new clone, on `$NEW_BR`:

    git fetch $OLD_CLONE refs/heads/$OLD_BR:refs/old/$OLD_BR refs/remotes/origin/main:refs/old/main
    git -c core.autocrlf=input cherry-pick -X renormalize \
        $(git rev-list --reverse --no-merges refs/old/main..refs/old/$OLD_BR)

    # afterwards: drop the old commits from the new clone (never pushed, but they take space)
    git for-each-ref --format='delete %(refname)' refs/old/ | git update-ref --stdin
    git gc --prune=now

## Alternative: move the branch inside your old clone (`remap-branch.sh`)

Useful for many branches at once, or to keep a branch's name and its open pull request. It works in your old clone,
which has the old commits the script needs, and uses the commit map to find where each branch starts in the new
history.

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

Undo either move with `git checkout $BR && git reset --hard refs/pre-rewrite/$BR`. Once every branch is moved:

    # 6. your main: reset it onto the new main (don't pull), and drop remote-tracking refs GitHub no longer has
    git checkout main && git reset --hard origin/main
    git fetch --prune origin

## Finding an old commit

`zfin-commit-map.txt` (in the NFS archive, `/research/zcentral/Vault/git/zfin.lfs.git/`) has one line per old
commit: `<old id> <new id> <kind>`. To find where an old commit went:

    grep "^<old id>" zfin-commit-map.txt

Most kinds (`fp`, `fp-from-ff-merge`, `release-NNNN`) mean the new commit has exactly the old commit's files.
`side-folded-into-merge` and `merge-single` point at the commit that now holds the change: a pull request's commits
were combined into one, with the files of its merge.
