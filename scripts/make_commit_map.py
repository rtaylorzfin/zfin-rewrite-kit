"""Compose the published old -> new commit map for the rewritten ZFIN history.

Usage (any cwd):
    python3 -I make_commit_map.py <source.git> <pre-LFS build.git> <final LFS repo.git> <build commit-map> <carry map> <out>

Inputs: the builder's commit-map (old -> pre-LFS new, with kind), carry_refs.py's map (branch commits),
and filter-repo's commit-map inside the final repo (pre-LFS new -> final new). Adds, for each old
release-NNNN tip, the commit its archive/release-NNNN tag points at (kind release-tip), so branches
started from a release branch can be moved too.

Output: header lines "# old-main <sha>" and "# old-release-NNNN <sha>", then "<old> <new> <kind>" per
line; new is "-" for commits that became empty and were dropped (look at their parent instead).
"""
import subprocess as sp, sys
SRC, PRE, FIN, BMAP, CMAP, OUT = sys.argv[1:7]
def git(repo, *a): return sp.run(['git', '-C', repo, *a], capture_output=True, text=True, check=True).stdout
fr = {}
for l in open(f'{FIN}/filter-repo/commit-map').read().splitlines()[1:]:
    o, n = l.split(); fr[o] = n
def final(c): return '-' if c == '-' else fr.get(c, c)   # unchanged commits are absent from filter-repo's map
m, kinds = {}, {}
for f in (BMAP, CMAP):
    for l in open(f):
        o, n, k = l.split()
        if o == '-': continue                               # reconcile snapshots have no old commit
        if o not in m or m[o] == '-': m[o] = final(n); kinds[o] = k
rels = sorted(r.split('/')[-1] for r in git(SRC, 'for-each-ref', '--format=%(refname)', 'refs/heads/release-*').split())
head = [f"# old-main {git(SRC, 'rev-parse', 'refs/heads/main').strip()}"]
for r in rels:
    tip = git(SRC, 'rev-parse', f'refs/heads/{r}').strip()
    t = sp.run(['git', '-C', PRE, 'rev-parse', '-q', '--verify', f'refs/tags/archive/{r}^{{commit}}'], capture_output=True, text=True)
    if t.returncode: print(f'{r}: no archive tag in the build (dropped), skipped'); continue
    head.append(f'# old-{r} {tip}')
    tag = t.stdout.strip()
    if tip not in m or kinds.get(tip) != 'fp': m[tip] = final(tag); kinds[tip] = 'release-tip'
with open(OUT, 'w') as f:
    f.write('# ZFIN history rewrite: old commit -> new commit. "-" = became empty and was dropped; use its parent.\n')
    f.write('\n'.join(head) + '\n')
    f.write(''.join(f'{o} {m[o]} {kinds[o]}\n' for o in m))
print(f'{len(m)} commits mapped ({sum(1 for v in m.values() if v == "-")} dropped-empty), {len(head) - 1} release tips -> {OUT}')
