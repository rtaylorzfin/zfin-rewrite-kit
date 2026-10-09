"""Verify an LFS-converted repo against its pre-conversion source, path by path.

Usage (cwd = the converted repo):
    python3 -I verify_lfs.py <pre-conversion repo> <pre-refs.txt>

<pre-refs.txt> holds "<refname> <object>" lines saved just before conversion (all tags and branches).
For every ref's tree, every path must be either
  - the identical blob, or
  - an LFS pointer whose object exists in lfs/objects and hashes (git hash-object) back to
    the original blob id, with the path listed in that tree's root .gitattributes.
Also: .gitattributes lists exactly the pointer paths, the commit count and per-commit
author/committer/message are unchanged (modulo filter-repo's
old->new hash translation inside messages), and main's tree is unchanged (no binaries at the tip were converted).
"""
import subprocess as sp, sys, os
pre, prerefs = sys.argv[1], sys.argv[2]
def git(*a, repo=None, inp=None):
    r = sp.run(['git'] + (['-C', repo] if repo else []) + list(a), capture_output=True, input=inp)
    if r.returncode: raise SystemExit(f"git {' '.join(a)} failed: {r.stderr.decode()}")
    return r.stdout
gitdir = git('rev-parse', '--absolute-git-dir').decode().strip()
lfs = os.path.join(gitdir, 'lfs', 'objects')

def tree(ref, repo=None):
    out = {}
    for l in git('ls-tree', '-r', '-z', '--full-tree', ref, repo=repo).split(b'\0'):
        if l:
            m, p = l.split(b'\t', 1); mode, typ, oid = m.split()
            out[p] = (mode, oid.decode())
    return out

def batch(oids):
    """Return {oid: content} for small blobs via cat-file --batch."""
    data = git('cat-file', '--batch', inp=''.join(o + '\n' for o in oids).encode())
    res = {}; i = 0
    for o in oids:
        nl = data.index(b'\n', i); hdr = data[i:nl].split(); size = int(hdr[2])
        res[o] = data[nl + 1:nl + 1 + size]; i = nl + 1 + size + 1
    return res

refs = [l.split() for l in open(prerefs)]
fails = []; hashed = {}; nptr_total = 0; checked = 0
for ref, _ in refs:
    if not (ref.startswith('refs/tags/') or ref.startswith('refs/heads/')): continue
    old, new = tree(ref, repo=pre), tree(ref)
    attrs = set()
    if b'.gitattributes' in new:
        body = batch([new[b'.gitattributes'][1]])[new[b'.gitattributes'][1]]
        for l in body.splitlines():
            p, *rest = l.split(b' ')
            assert rest == [b'filter=lfs', b'diff=lfs', b'merge=lfs', b'-text'], l
            attrs.add(p[1:].replace(b'[[:space:]]', b' '))
    if b'.gitattributes' in old: fails.append(f"{ref}: source already had .gitattributes")
    newpaths = set(new) - {b'.gitattributes'}
    if newpaths != set(old): fails.append(f"{ref}: path sets differ"); continue
    changed = [p for p in old if old[p] != new[p]]
    ptrs = batch(sorted({new[p][1] for p in changed})) if changed else {}
    for p in changed:
        if old[p][0] != new[p][0]: fails.append(f"{ref}: {p!r} mode changed"); continue
        body = ptrs[new[p][1]].decode(errors='replace').splitlines()
        if len(body) != 3 or body[0] != 'version https://git-lfs.github.com/spec/v1' or not body[1].startswith('oid sha256:'):
            fails.append(f"{ref}: {p!r} changed but is not an LFS pointer"); continue
        oid = body[1][len('oid sha256:'):]; f = os.path.join(lfs, oid[:2], oid[2:4], oid)
        if not os.path.exists(f): fails.append(f"{ref}: {p!r} LFS object {oid} missing"); continue
        if os.path.getsize(f) != int(body[2].split()[1]): fails.append(f"{ref}: {p!r} size mismatch")
        if oid not in hashed: hashed[oid] = git('hash-object', f).decode().strip()
        if hashed[oid] != old[p][1]: fails.append(f"{ref}: {p!r} LFS object does not hash to original blob")
        if p not in attrs: fails.append(f"{ref}: {p!r} is a pointer but not in .gitattributes")
    if attrs != set(changed): fails.append(f"{ref}: .gitattributes lists {len(attrs)} paths, {len(changed)} pointers")
    nptr_total += len(changed); checked += 1
    print(f"{ref}: {len(old)} paths, {len(changed)} LFS pointers", flush=True)

# history shape and metadata
fmt = '--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd%x00%B%x01'
a = git('log', '--date=raw', fmt, 'main', repo=pre); b = git('log', '--date=raw', fmt, 'main')
# filter-repo rewrites hashes of rewritten commits inside messages (e.g. our "[linear history] ... applied
# earlier as <sha>" notes); translate those through its commit-map before comparing.
cm = dict(l.split() for l in open(os.path.join(gitdir, 'filter-repo', 'commit-map')).read().splitlines()[1:])
def xlate(x):
    for o, n in cm.items():
        if o != n and o.encode() in x: x = x.replace(o.encode(), n.encode())
    return x
if xlate(a) != b: fails.append("main: commit metadata/messages differ (beyond filter-repo's hash translation)")
if git('rev-parse', 'main^{tree}', repo=pre) != git('rev-parse', 'main^{tree}'): fails.append("main tip tree changed")
for ref, _ in refs:
    if ref.startswith('refs/tags/'):
        if git('cat-file', '-t', ref, repo=pre).strip() == b'tag':   # annotated: compare all but the object line
            same = xlate(git('cat-file', '-p', ref, repo=pre).split(b'\n', 1)[1]) == git('cat-file', '-p', ref).split(b'\n', 1)[1]
        else:                                                           # lightweight: compare the commit's metadata
            same = xlate(git('log', '-1', '--date=raw', fmt, ref, repo=pre)) == git('log', '-1', '--date=raw', fmt, ref)
        if not same: fails.append(f"{ref}: tag object / tagged commit metadata differs")

print(f"\nrefs checked: {checked}   pointer paths verified: {nptr_total}   distinct LFS objects hashed: {len(hashed)}")
lfsbytes = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(lfs) for f in fs)
print(f"lfs/objects: {sum(len(fs) for _, _, fs in os.walk(lfs))} files, {lfsbytes / 1048576:.0f} MB")
print("FAIL\n  " + "\n  ".join(fails[:50]) if fails else "ok   every tag byte-identical after LFS smudge; main unchanged")
sys.exit(1 if fails else 0)
