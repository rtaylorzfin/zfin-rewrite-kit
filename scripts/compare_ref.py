"""Compare the files of one commit, branch or tag between the old repo and the rewritten one.

Usage:
    python3 -I compare_ref.py <old repo> <old ref> <new repo> <new ref>

Path by path, a file counts as identical when it has the same blob id (same bytes) in both, or when the new
file is a Git LFS pointer whose sha256 and size are those of the old file's bytes (what git-lfs restores on
checkout). A file that is the old text with LF line endings (the rewrite's line-ending fix: CRLF, or classic-Mac CR, -> LF)
is counted separately and also passes. The .gitattributes that the LFS step adds to old commits is reported but not counted as a difference.
Exit code 0 when every file is identical.
"""
import hashlib, subprocess as sp, sys

OLD, OLD_REF, NEW, NEW_REF = sys.argv[1:5]

def tree(repo, ref):
    out = sp.run(['git', '-C', repo, 'ls-tree', '-r', '-z', ref], capture_output=True, check=True).stdout
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

def to_lf(data):   # the rewrite's line-ending fix (lfs_convert.py): CRLF -> LF, or classic-Mac CR -> LF
    if b'\0' in data[:8000]: return data
    if b'\r\n' in data: return data.replace(b'\r\n', b'\n')
    if b'\r' in data and b'\n' not in data: return data.replace(b'\r', b'\n')
    return data

def lfs_pointer(data):   # (sha256, size) if data is a Git LFS pointer, else None
    if len(data) > 200 or not data.startswith(b'version https://git-lfs'): return None
    f = dict(l.split(b' ', 1) for l in data.splitlines() if b' ' in l)
    return f[b'oid'].split(b':')[1].decode(), int(f[b'size'])

old, new = tree(OLD, OLD_REF), tree(NEW, NEW_REF)
same = via_lfs = eol = 0; problems = []
for path in sorted(set(old) | set(new)):
    if path == '.gitattributes' and path not in old:
        print('note: .gitattributes added by the LFS step (lists the LFS paths; not in the original)'); continue
    if path not in new: problems.append(f'missing in new: {path}'); continue
    if path not in old: problems.append(f'extra in new:   {path}'); continue
    (om, oo), (nm, no) = old[path], new[path]
    if om != nm: problems.append(f'mode differs:   {path} ({om} vs {nm})'); continue
    if oo == no: same += 1; continue
    new_data = blob(NEW, no); ptr = lfs_pointer(new_data); data = blob(OLD, oo)
    if ptr and ptr == (hashlib.sha256(data).hexdigest(), len(data)): via_lfs += 1
    elif not ptr and to_lf(data) == new_data: eol += 1
    else: problems.append(f'content differs: {path}')

print(f'{OLD_REF} -> {NEW_REF}: {len(old)} files; {same} identical, {via_lfs} identical via LFS pointer, '
      f'{eol} identical apart from line endings, {len(problems)} different')
for p in problems[:20]: print('  ' + p)
sys.exit(1 if problems else 0)
