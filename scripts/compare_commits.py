"""Check old commits against their rewritten counterparts, using the commit map.

Usage:
    python3 -I compare_commits.py <zfin-commit-map.txt> <old repo> <new repo> [<old commit> ...]
    python3 -I compare_commits.py <zfin-commit-map.txt> <old repo> <new repo> --sample N [--seed S]
    (either form takes --list, to also name the files that differ only in line endings or whitespace)

<old repo> and <new repo> may be the same clone (an old clone with the new history fetched into it: `.` and `.`).
Old commits may be abbreviated. With --sample, N mapped commits are picked at random (--seed repeats a pick).

For each old commit, the map gives its new commit, and every path is compared. A file counts as identical when
its bytes are the same, or the new file is a Git LFS pointer to the old file's bytes. When it is not, the file is
classed by the weakest difference that explains it:
    eol         identical once line endings are converted to LF (CRLF, or classic-Mac CR, -> LF)
    whitespace  identical once all whitespace is removed (spaces, tabs, line breaks)
    content     a real difference
eol and whitespace differences are counted (named with --list) but pass; the exit code is 1 only for content, mode or missing/extra
paths. The .gitattributes that the rewrite adds is reported, not counted.

Two map kinds point at a different state on purpose (side-folded-into-merge, merge-single: the new commit has the
merge's files); they are compared and reported, but their differences don't fail the run. A "-" in the map means
the commit became empty and was dropped; it is skipped.
"""
import hashlib, random, re, subprocess as sp, sys

args = sys.argv[1:]
sample = seed = None
list_all = '--list' in args
if list_all: args.remove('--list')
if '--sample' in args: i = args.index('--sample'); sample = int(args[i + 1]); del args[i:i + 2]
if '--seed' in args: i = args.index('--seed'); seed = int(args[i + 1]); del args[i:i + 2]
if len(args) < 3 or (sample is None) == (len(args) == 3):
    sys.exit(__doc__)
MAP, OLD, NEW, wanted = args[0], args[1], args[2], args[3:]
BY_DESIGN = {'side-folded-into-merge', 'merge-single'}

entries = {}   # old -> (new, kind)
for line in open(MAP):
    if line.startswith('#') or not line.strip(): continue
    o, n, k = line.split()
    entries[o] = (n, k)

def lookup(prefix):
    if prefix in entries: return prefix
    hits = [o for o in entries if o.startswith(prefix)]
    if len(hits) != 1: sys.exit(f'{prefix}: {"not in the map" if not hits else "ambiguous"}')
    return hits[0]

if sample is not None:
    pool = sorted(o for o, (n, _) in entries.items() if n != '-')
    todo = random.Random(seed).sample(pool, min(sample, len(pool)))
else:
    todo = [lookup(c) for c in wanted]

def tree(repo, commit):
    out = sp.run(['git', '-C', repo, 'ls-tree', '-r', '-z', commit], capture_output=True, check=True).stdout
    files = {}
    for entry in out.split(b'\0'):
        if entry:
            info, path = entry.split(b'\t', 1); mode, kind, oid = info.split()
            files[path.decode(errors='surrogateescape')] = (mode.decode(), oid.decode())
    return files

readers = {}
def blob(repo, oid):   # one long-running `git cat-file --batch` per repo
    if repo not in readers:
        readers[repo] = sp.Popen(['git', '-C', repo, 'cat-file', '--batch'], stdin=sp.PIPE, stdout=sp.PIPE)
    r = readers[repo]; r.stdin.write(oid.encode() + b'\n'); r.stdin.flush()
    size = int(r.stdout.readline().split()[2]); data = r.stdout.read(size); r.stdout.read(1)
    return data

def lfs_pointer(data):   # (sha256, size) if data is a Git LFS pointer, else None
    if len(data) > 200 or not data.startswith(b'version https://git-lfs'): return None
    f = dict(l.split(b' ', 1) for l in data.splitlines() if b' ' in l)
    return f[b'oid'].split(b':')[1].decode(), int(f[b'size'])

def to_lf(data):   # the rewrite's line-ending fix (lfs_convert.py): CRLF -> LF, or classic-Mac CR -> LF
    if b'\0' in data[:8000]: return data
    if b'\r\n' in data: return data.replace(b'\r\n', b'\n')
    if b'\r' in data and b'\n' not in data: return data.replace(b'\r', b'\n')
    return data

WS = re.compile(rb'\s+')
verdicts = {}   # (old oid, new oid) -> 'same' | 'lfs' | 'eol' | 'whitespace' | 'content'
def compare_blobs(oo, no):
    if oo == no: return 'same'
    if (oo, no) not in verdicts:
        old, new = blob(OLD, oo), blob(NEW, no)
        ptr = lfs_pointer(new)
        if ptr: v = 'lfs' if ptr in ((hashlib.sha256(d).hexdigest(), len(d)) for d in (old, to_lf(old))) else 'content'
        elif to_lf(old) == to_lf(new): v = 'eol'
        elif WS.sub(b'', old) == WS.sub(b'', new): v = 'whitespace'
        else: v = 'content'
        verdicts[oo, no] = v
    return verdicts[oo, no]

failed = 0
for o in todo:
    n, kind = entries[o]
    if n == '-': print(f'{o[:10]} -> -           [{kind}] dropped as empty; check its parent instead'); continue
    old, new = tree(OLD, o), tree(NEW, n)
    counts = dict.fromkeys(('same', 'lfs', 'eol', 'whitespace', 'content'), 0); problems = []
    for path in sorted(set(old) | set(new)):
        if path == '.gitattributes' and path not in old: continue
        if path not in new: problems.append(f'missing in new: {path}'); continue
        if path not in old: problems.append(f'extra in new:   {path}'); continue
        (om, oo), (nm, no) = old[path], new[path]
        if om != nm: problems.append(f'mode differs:   {path} ({om} vs {nm})'); continue
        v = compare_blobs(oo, no); counts[v] += 1
        if v in ('eol', 'whitespace', 'content'): problems.append(f'{v + ":":15} {path}')
    real = [p for p in problems if not p.startswith(('eol:', 'whitespace:'))]
    status = 'ok' if not real else ('differs by design' if kind in BY_DESIGN else 'DIFFERS')
    failed += bool(real) and kind not in BY_DESIGN
    print(f'{o[:10]} -> {n[:10]} [{kind}] {status}: {len(old)} files; {counts["same"]} identical, '
          f'{counts["lfs"]} via LFS pointer, {counts["eol"]} line endings only, {counts["whitespace"]} whitespace only, '
          f'{len(real)} different')
    shown = problems if list_all else real
    for p in shown[:10]: print('    ' + p)
    if len(shown) > 10: print(f'    ... {len(shown) - 10} more')

print(f'{len(todo)} commit(s) checked, {failed} with real differences')
sys.exit(1 if failed else 0)
