"""Verify an LFS-converted repo against its pre-conversion source, path by path.

Usage (cwd = the converted repo):
    python3 -I verify_lfs.py <pre-conversion repo> <pre-refs.txt>

<pre-refs.txt> holds "<refname> <object>" lines saved just before conversion (all tags and branches).
For every ref's tree, every path must be either
  - the identical blob, or
  - the original text with LF line endings (lfs_convert.py's to_lf: CRLF or classic-Mac CR -> LF), or
  - an LFS pointer whose object exists in lfs/objects and hashes (git hash-object) back to
    the original blob id, with the path listed in that tree's root .gitattributes.
Also: .gitattributes lists exactly the pointer paths, the commit count and per-commit
author/committer/message are unchanged (modulo filter-repo's old->new hash translation inside messages),
main has no LFS pointers (no binaries at the tip were converted), and every text file in main has LF endings.
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

def batch(oids, repo=None):
    """Return {oid: content} for the blobs via cat-file --batch."""
    data = git('cat-file', '--batch', inp=''.join(o + '\n' for o in oids).encode(), repo=repo)
    res = {}; i = 0
    for o in oids:
        nl = data.index(b'\n', i); hdr = data[i:nl].split(); size = int(hdr[2])
        res[o] = data[nl + 1:nl + 1 + size]; i = nl + 1 + size + 1
    return res

refs = [l.split() for l in open(prerefs)]
def to_lf(data):   # the rewrite's line-ending fix (lfs_convert.py): CRLF -> LF, or classic-Mac CR -> LF
    if b'\0' in data[:8000]: return data
    if b'\r\n' in data: return data.replace(b'\r\n', b'\n')
    if b'\r' in data and b'\n' not in data: return data.replace(b'\r', b'\n')
    return data
def is_pointer(data): return data.startswith(b'version https://git-lfs.github.com/spec/v1\n') and len(data) < 200
eol_ok = {}   # (old blob, new blob) -> True if new is old with CRLF -> LF; shared by every ref
fails = []; hashed = {}; nptr_total = 0; neol_total = 0; checked = 0
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
    todo = {(old[p][1], new[p][1]) for p in changed if not is_pointer(ptrs[new[p][1]])} - set(eol_ok)
    olds = batch(sorted({o for o, _ in todo}), repo=pre) if todo else {}
    for o, n in todo:
        d = olds[o]; eol_ok[o, n] = to_lf(d) != d and to_lf(d) == ptrs[n]
    eol = []
    for p in changed:
        if old[p][0] != new[p][0]: fails.append(f"{ref}: {p!r} mode changed"); continue
        if eol_ok.get((old[p][1], new[p][1])): eol.append(p); continue
        body = ptrs[new[p][1]].decode(errors='replace').splitlines()
        if len(body) != 3 or body[0] != 'version https://git-lfs.github.com/spec/v1' or not body[1].startswith('oid sha256:'):
            fails.append(f"{ref}: {p!r} changed but is neither an LFS pointer nor the same text with LF endings"); continue
        oid = body[1][len('oid sha256:'):]; f = os.path.join(lfs, oid[:2], oid[2:4], oid)
        if not os.path.exists(f): fails.append(f"{ref}: {p!r} LFS object {oid} missing"); continue
        if os.path.getsize(f) != int(body[2].split()[1]): fails.append(f"{ref}: {p!r} size mismatch")
        if oid not in hashed: hashed[oid] = git('hash-object', f).decode().strip()
        if hashed[oid] != old[p][1]: fails.append(f"{ref}: {p!r} LFS object does not hash to original blob")
        if p not in attrs: fails.append(f"{ref}: {p!r} is a pointer but not in .gitattributes")
    pointers = set(changed) - set(eol)
    if attrs != pointers: fails.append(f"{ref}: .gitattributes lists {len(attrs)} paths, {len(pointers)} pointers")
    if ref == 'refs/heads/main':
        if pointers: fails.append(f"main has {len(pointers)} LFS pointers; the tip must have none")
        notlf = [p for p, d in batch(sorted({new[p][1] for p in newpaths})).items() if to_lf(d) != d]
        if notlf: fails.append(f"main still has {len(notlf)} text blobs with CRLF or CR line endings")
    nptr_total += len(pointers); neol_total += len(eol); checked += 1
    print(f"{ref}: {len(old)} paths, {len(pointers)} LFS pointers, {len(eol)} with LF endings now", flush=True)

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
for ref, _ in refs:
    if ref.startswith('refs/tags/'):
        if git('cat-file', '-t', ref, repo=pre).strip() == b'tag':   # annotated: compare all but the object line
            same = xlate(git('cat-file', '-p', ref, repo=pre).split(b'\n', 1)[1]) == git('cat-file', '-p', ref).split(b'\n', 1)[1]
        else:                                                           # lightweight: compare the commit's metadata
            same = xlate(git('log', '-1', '--date=raw', fmt, ref, repo=pre)) == git('log', '-1', '--date=raw', fmt, ref)
        if not same: fails.append(f"{ref}: tag object / tagged commit metadata differs")

print(f"\nrefs checked: {checked}   pointer paths verified: {nptr_total}   LF-ending paths verified: {neol_total}   "
      f"distinct LFS objects hashed: {len(hashed)}")
lfsbytes = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(lfs) for f in fs)
print(f"lfs/objects: {sum(len(fs) for _, _, fs in os.walk(lfs))} files, {lfsbytes / 1048576:.0f} MB")
print("FAIL\n  " + "\n  ".join(fails[:50]) if fails else
      "ok   every tag byte-identical after LFS smudge, apart from line endings; main has no LFS pointers, only LF endings")
sys.exit(1 if fails else 0)
