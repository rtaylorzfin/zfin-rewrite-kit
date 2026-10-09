"""First-parent rewrite: main = old main's first-parent line, releases = their own commits on the real cut.

Usage (cwd = new bare repo whose alternates reach the source objects):
    python3 -I build_fp.py <source.git> <out-dir>

No hoisting and no patching: every new commit reuses the ORIGINAL commit's tree, only the parent changes.
  main      every first-parent commit of old main, in order, same tree, author, committer, dates, message.
            A merge (decided 2026-10-09):
            - fast-forwardable (nothing landed on main between the branch point and the merge, merge files = the
              branch tip's, no merges on the branch): the branch's own commits go on main unchanged instead;
            - one commit on the branch: one commit with the merge's files and that commit's author, committer,
              dates and message, plus a note naming the merge (so blame and log show the real change);
            - otherwise: an ordinary commit with the merge's files whose message gets a note listing the commits
              it folded in (they are not on the new main).
            Every commit on main therefore has the files of a commit that really existed.
  releases  for each refs/heads/release-NNNN except SKIP: walk the release's first-parent chain back to the
            first commit on old main's first-parent line (the cut), replay the release's own commits on the new
            copy of the cut (same trees), and tag the result archive/release-NNNN (annotated, as build_linear.py).
Writes <out-dir>/commit-map.txt ("<old> <new> <kind>"; kinds fp, fp-from-ff-merge, merge-ff, merge-single,
merge-folded, release-NNNN, side-folded-into-merge) and <out-dir>/build-report.json, and checks every tree on the way.
"""
import subprocess as sp, sys, os, json
SRC, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
SKIP = {'release-1123'}   # 1123 carries master's 1998-2021 CVS/SVN history; dropped (decided 2026-10-09)
def g(*a, inp=None, e=None): return sp.run(['git', *a], capture_output=True, input=inp, env=e)
def out(*a): return g(*a).stdout.decode().strip()
def s(*a): return sp.run(['git', '-C', SRC, *a], capture_output=True).stdout.decode().strip()
def _ident(line):
    lt = line.rindex(b' <'); gt = line.rindex(b'> ')
    return line[:lt].decode(errors='surrogateescape'), line[lt + 2:gt].decode(errors='surrogateescape'), line[gt + 2:].decode()
_meta = {}
def meta(c):
    # raw commit object, so the message stays byte-exact; gpgsig headers are not carried
    if c not in _meta:
        raw = g('cat-file', 'commit', c).stdout
        head, msg = raw.split(b'\n\n', 1); h = {}
        for ln in head.split(b'\n'):
            if ln[:1] == b' ': continue
            k, _, v = ln.partition(b' '); h.setdefault(k, v)
        _meta[c] = (*_ident(h[b'author']), *_ident(h[b'committer']), msg, h[b'tree'].decode())
    return _meta[c]
def commit(c, parent, msg=None, tree=None):
    an, ae, ad, cn, ce, cd, m, own_tree = meta(c); tree = tree or own_tree
    e = dict(os.environ, GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae, GIT_AUTHOR_DATE=ad,
             GIT_COMMITTER_NAME=cn, GIT_COMMITTER_EMAIL=ce, GIT_COMMITTER_DATE=cd)
    r = g('commit-tree', tree, *(['-p', parent] if parent else []), '-F', '-', inp=msg if msg is not None else m, e=e)
    if r.returncode: raise SystemExit(f'commit-tree failed for {c}: ' + r.stderr.decode())
    return r.stdout.decode().strip()

g('fetch', '-q', '--no-tags', SRC, 'refs/heads/main:refs/source/main', 'refs/heads/release-*:refs/source/release-*')
cmap = {}   # old -> (new, kind); first writer wins, release copies are written before folded side commits
def put(o, n, k): cmap.setdefault(o, (n, k))

# ---- main
fp = out('rev-list', '--first-parent', '--reverse', 'refs/source/main').split()
fpset = set(fp); new = {}; head = None; folded = {}
expect = []   # (new main commit, the old commit whose files it must have), checked below
def is_merge(x): return len(out('rev-parse', x + '^@').split()) > 1
for c in fp:
    ps = out('rev-parse', c + '^@').split()
    side = out('rev-list', '--reverse', '--topo-order', f'{ps[0]}..{c}', '--not', *ps[:1]).split() if len(ps) > 1 else []
    side = [x for x in side if x != c]
    if (len(ps) == 2 and out('merge-base', ps[0], ps[1]) == ps[0] and meta(c)[7] == meta(ps[1])[7]
            and not any(is_merge(x) for x in side)):
        for x in side:   # fast-forwardable merge: keep the branch's own commits, unchanged
            head = commit(x, head); put(x, head, 'fp-from-ff-merge'); expect.append((head, x))
        put(c, head, 'merge-ff')
    elif len(ps) > 1 and len(side) == 1 and not is_merge(side[0]):
        x = side[0]; mm = meta(c)
        msubj = mm[6].decode(errors='replace').strip().splitlines()[0]
        mdate = out('log', '-1', '--format=%as', c)
        note = (f'\n[linear history] Landed on main as merge {c[:10]} "{msubj}" ({mm[0]}, {mdate});\n'
                'this commit has that merge\'s files.\n')
        head = commit(x, head, msg=meta(x)[6].rstrip(b'\n') + b'\n' + note.encode(), tree=mm[7])
        put(x, head, 'merge-single'); put(c, head, 'merge-single'); expect.append((head, c))
    elif len(ps) > 1:
        folded[c] = side
        lines = []
        for x in side:
            an, _, ad, *_ , m, _t = meta(x)
            subj = m.decode(errors='replace').strip().splitlines()[0] if m.strip() else ''
            lines.append(f'  {x[:10]} {an}: {subj[:72]}')
        note = ('\n[linear history] This merge is now a single commit with the same files. It folded in '
                f'{len(side)} commit(s) from the merged branch\n(old ids; see zfin-commit-map.txt):\n' + '\n'.join(lines) + '\n')
        m = meta(c)[6]
        head = commit(c, head, msg=m.rstrip(b'\n') + b'\n' + note.encode())
        put(c, head, 'merge-folded'); expect.append((head, c))
    else:
        head = commit(c, head); put(c, head, 'fp'); expect.append((head, c))
    new[c] = head
g('update-ref', 'refs/heads/main', head)

# ---- releases
rel = {}
for r in sorted(out('for-each-ref', '--format=%(refname:short)', 'refs/source/release-*').split()):
    name = r.split('/')[-1]
    if name in SKIP: continue
    n = name.split('-')[1]; tip = out('rev-parse', r); chain = []; c = tip
    while c not in fpset:
        if len(out('rev-parse', c + '^@').split()) > 1: raise SystemExit(f'{name}: merge {c} on its first-parent line; not handled')
        chain.append(c); c = out('rev-parse', c + '^1')
        if not c or len(chain) > 500: raise SystemExit(f'{name}: no cut found on main first-parent')
    cut = c; chain.reverse(); h = new[cut]
    for x in chain:
        h = commit(x, h); put(x, h, f'release-{n}')
    assert out('rev-parse', h + '^{tree}') == out('rev-parse', tip + '^{tree}'), name
    an, ae, ad, cn, ce, cd, *_ = meta(tip)
    te = dict(os.environ, GIT_COMMITTER_NAME=cn, GIT_COMMITTER_EMAIL=ce, GIT_COMMITTER_DATE=cd)
    g('tag', '-f', '-a', f'archive/release-{n}', '-m',
      f'ZFIN release {n}\n\nDeployed state: identical tree to the original release-{n} tip {tip}.\n', h, e=te)
    rel[n] = dict(cut=cut, new_cut=new[cut], commits=len(chain), on_main=(len(chain) == 0))
    print(f'release {n}: cut {cut[:10]}, {len(chain)} commit(s) off main', flush=True)

# side commits of folded merges that are not on any release: map to the commit that now holds their change
for mc, side in folded.items():
    for x in side: put(x, new[mc], 'side-folded-into-merge')

# ---- checks
newfp = out('rev-list', '--first-parent', '--reverse', 'main').split()
assert newfp == [nw for nw, _ in expect] and not out('rev-list', '--merges', 'main'), 'main not linear / unexpected commits'
bad = [o for nw, o in expect if meta(o)[7] != out('rev-parse', nw + '^{tree}')]
assert not bad, f'tree mismatch on main: {bad[:5]}'
with open(f'{OUT}/commit-map.txt', 'w') as f:
    f.write(''.join(f'{o} {nw} {k}\n' for o, (nw, k) in cmap.items()))
json.dump(dict(rel=rel, folded={k: v for k, v in folded.items()}), open(f'{OUT}/build-report.json', 'w'), indent=1)
off = sum(v['commits'] for v in rel.values())
kinds = [k for _, k in cmap.values()]
print(f'main: {len(newfp)} commits, linear, every tree identical to an original commit; merges: '
      f'{kinds.count("merge-ff")} fast-forwardable ({kinds.count("fp-from-ff-merge")} commits kept), '
      f'{kinds.count("merge-single") // 2} single-commit, {len(folded)} folded ({sum(len(v) for v in folded.values())} side commits)')
print(f'releases: {len(rel)} tags, {sum(1 for v in rel.values() if v["on_main"])} on main, {off} commits off main '
      f'(max {max(v["commits"] for v in rel.values())})')
