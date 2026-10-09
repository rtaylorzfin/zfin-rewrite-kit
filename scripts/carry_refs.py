"""Carry feature branches (and any CARRY_TAGS) onto a built linear history.

Usage (cwd = build repo; its alternates must reach the source objects):
    python3 -I carry_refs.py <source.git> <commit-map.txt> <out-commit-map.txt>

Branches = every refs/heads/* in <source.git> except main, release-* and DROP. For each:
  base  = merge-base(main, branch) in the source; new base = its commit-map entry (a dropped-empty
          commit maps through its first parent).
  The branch's own commits are re-applied on the new base (strict `git apply`, no 3-way), so the
  branch shows exactly the author's changes against the new main. If any commit does not apply,
  the whole branch is instead rebuilt from the original trees (tip byte-identical; the first
  commit then also carries whatever differs between the old and the new base).
Tags in CARRY_TAGS = the vNNNN tags (GitHub Releases, archived at Zenodo; decided 2026-10-08), lightweight as before:
  a tag whose files equal a release tag's points at that archive/release-NNNN commit; else at the mapped commit
  if its tree is identical; else at a one-commit snapshot with exactly the original tree on top of the mapped
  commit. (main-before-tomcat10-upgrade was dropped.)
Author, committer, dates and message bytes come from the source commit (gpgsig dropped).
"""
import subprocess as sp, sys, os
SRCREPO, MAPF, OUTF = sys.argv[1], sys.argv[2], sys.argv[3]
env = dict(os.environ, GIT_INDEX_FILE=os.path.abspath(OUTF + '.idx'))
def g(*a, inp=None, e=None): return sp.run(['git', *a], capture_output=True, input=inp, env=e or env)
def out(*a): return g(*a).stdout.decode().strip()
def src(*a): return sp.run(['git', '-C', SRCREPO, *a], capture_output=True, text=True).stdout.strip()
def wt():
    r = g('write-tree')
    if r.returncode: raise SystemExit('write-tree failed: ' + r.stderr.decode())
    return r.stdout.decode().strip()
def cdiff(a, b): return g('diff', '--binary', '--full-index', a, b).stdout
def _ident(line):
    lt = line.rindex(b' <'); gt = line.rindex(b'> ')
    return line[:lt].decode(errors='surrogateescape'), line[lt + 2:gt].decode(errors='surrogateescape'), line[gt + 2:].decode()
def commit(tree, parent, like, message=None):
    raw = g('cat-file', 'commit', like).stdout
    head, msg = raw.split(b'\n\n', 1); h = {}
    for ln in head.split(b'\n'):
        if ln[:1] == b' ': continue
        k, _, v = ln.partition(b' '); h.setdefault(k, v)
    an, ae, ad = _ident(h[b'author']); cn, ce, cd = _ident(h[b'committer'])
    e = dict(env, GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae, GIT_AUTHOR_DATE=ad, GIT_COMMITTER_NAME=cn, GIT_COMMITTER_EMAIL=ce, GIT_COMMITTER_DATE=cd)
    r = g('commit-tree', tree, '-p', parent, '-F', '-', inp=message.encode() if message else msg, e=e)
    if r.returncode: raise SystemExit('commit-tree failed: ' + r.stderr.decode())
    return r.stdout.decode().strip()

cmap = {}
for l in open(MAPF):
    o, n, k = l.split()
    if o != '-' and n != '-': cmap.setdefault(o, n)
def mapped(c):
    while c not in cmap:          # dropped-empty commits: same state as their first parent
        c = src('rev-parse', c + '^1')
    return cmap[c]

newmap = []; report = []
# blastZfinDBs: nothing to recover (47a7c3a8cc is all on main; d7333f023e only fixes unused duplicate
# BLAST scripts) and its commits don't re-apply, so it would carry old trees that undo hoisted fixes.
# The other seven: every commit already on main as an exact patch-id twin (merged PR branches never deleted;
# zfin-7894 has no commits of its own).
DROP = {'blastZfinDBs',
        'eola', 'jbrowse', 'zfin-7894', 'ZFIN-9555', 'FixGff3', 'ZFIN-10048', 'ZFIN-10497',
        # GitHub-stale branches (no activity in months; old work kept only in the as-is archive), and solr9
        # (Solr 9 upgrade already done on main by ZFIN-10276).
        'efg-colors', 'publicationMeta', 'zfin-7834', 'ZFIN-7934', 'zfin-8412', 'zfin-8174', 'tuneUiIndexer',
        'ubertable', 'ZFIN-8806', 'zfin-8915-old', 'zfin-8916', 'ZFIN-9155', 'textpresso', 'zfin-9270',
        'ZFIN-9402', 'schlapp', 'grcz12', 'ZFIN-9457', 'zirc', 'solr9'}   # decided 2026-10-08
branches = [b for b in src('for-each-ref', '--format=%(refname:short)', 'refs/heads/').split()
            if b != 'main' and not b.startswith('release-') and b not in DROP]
for b in branches:
    tip = src('rev-parse', b); base = src('merge-base', 'main', b)
    cs = src('rev-list', '--reverse', '--topo-order', f'{base}..{tip}').split()
    if src('rev-list', '--merges', f'{base}..{tip}'): raise SystemExit(f'{b}: contains merges; not handled')
    nb = mapped(base); head = nb; mode = 'patch'; new = []
    g('read-tree', nb)
    for c in cs:
        if g('apply', '--cached', '-', inp=cdiff(c + '^1', c)).returncode != 0: mode = 'exact'; break
        head = commit(wt(), head, c); new.append((c, head))
    if mode == 'exact':
        head = nb; new = []
        for c in cs:
            head = commit(out('rev-parse', c + '^{tree}'), head, c); new.append((c, head))
    g('update-ref', f'refs/heads/{b}', head)
    newmap += [(o, n, f'branch-{b}' + ('-exact-trees' if mode == 'exact' else '')) for o, n in new]
    same_tip = out('rev-parse', head + '^{tree}') == out('rev-parse', tip + '^{tree}')
    same_diff = cdiff(base, tip) == cdiff(nb, head)
    report.append(f"{b:32} {len(cs):3} commits  mode={mode:5}  diff-vs-base identical={same_diff}  tip tree identical={same_tip}")

# vNNNN tags: GitHub Releases 1175+ (and their Zenodo records) are attached to them, and Zenodo links to tree/vNNNN.
# They are force-updated in place at cutover, never deleted (a Release whose tag disappears turns into a draft, and
# re-publishing it would mint a new Zenodo version).
CARRY_TAGS = sorted(src('for-each-ref', '--format=%(refname:short)', 'refs/tags/v[0-9]*').split())
archive_by_tree = {}
for r in out('for-each-ref', '--format=%(refname)', 'refs/tags/archive/').split():
    archive_by_tree.setdefault(out('rev-parse', r + '^{tree}'), (r.split('/')[-1], out('rev-parse', r + '^{commit}')))
for t in CARRY_TAGS:
    c = src('rev-parse', t + '^{commit}'); ct = out('rev-parse', c + '^{tree}'); m = mapped(c)
    if ct in archive_by_tree: name, target = archive_by_tree[ct]; how = f'archive/{name} commit (identical tree)'
    elif out('rev-parse', m + '^{tree}') == ct: target = m; how = 'mapped commit (identical tree)'
    else:
        subj = out('log', '-1', '--format=%s', c)
        target = commit(out('rev-parse', c + '^{tree}'), m, c,
            message=f"Snapshot: {t}\n\nIdentical tree to the original commit {c}\n(\"{subj}\"), which the tag {t} marked.\n"
                    f"In the rewritten history the matching point is {m}; its files differ slightly\nbecause release hotfixes were moved earlier.\n")
        newmap.append((c, target, 'tag-snapshot-' + t)); how = f'one-commit snapshot on {m[:10]}'
    g('update-ref', f'refs/tags/{t}', target)
    report.append(f"{t}: {how}; tree identical={out('rev-parse', target + '^{tree}') == out('rev-parse', c + '^{tree}')}")

open(OUTF, 'w').write(''.join(f'{o} {n} {k}\n' for o, n, k in newmap))
if os.path.exists(env['GIT_INDEX_FILE']): os.remove(env['GIT_INDEX_FILE'])
print('\n'.join(report))
