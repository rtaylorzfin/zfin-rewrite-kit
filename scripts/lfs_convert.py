"""Convert specific historical blobs to Git LFS pointers, and every other text blob's CRLF line endings to LF,
in place, with git-filter-repo.

Usage (cwd = the repo to rewrite; run on a disposable copy):
    python3 -I lfs_convert.py [--no-attributes] <blob-id-list> [<filter-repo script path>]

--no-attributes: write pointers only, never a .gitattributes. Pointers are then inert text for
everyone (no LFS filter ever runs, even for people with git-lfs or a leftover
filter.lfs.required=true); restoring an old release's binaries is opt-in (restore_lfs.sh).

- Only blobs whose original id is in <blob-id-list> are converted (so binaries still at the
  tip, which are not in the list, stay ordinary git blobs).
- LFS objects are written to <git-dir>/lfs/objects/<oid[0:2]>/<oid[2:4]>/<oid>, which is where
  git-lfs looks for them, so `git lfs push --all` can upload them later.
- Every commit gets a root .gitattributes listing exactly the converted paths present in its
  tree (`/path filter=lfs diff=lfs merge=lfs -text`), so checking out an old tag with git-lfs
  installed restores the real files. Commits without converted files get no .gitattributes,
  so new jars are NOT routed to LFS automatically. (This repo has never had a .gitattributes.)
- Every other blob that is text (no NUL byte and few non-printable bytes, git's own test) gets LF line endings, in
  every commit: each CRLF becomes LF, and in a file whose lines end in CR alone (classic Mac, no LF anywhere)
  each CR becomes LF. A lone CR inside a file with LF lines is data and stays. History then starts out with LF
  endings, and blame looks through commits that only changed line endings. Blobs moved to LFS keep their
  original bytes.
- filter-repo writes .git/filter-repo/commit-map (old -> new) as usual.
"""
import sys, os, shutil, subprocess, hashlib, importlib.util, importlib.machinery
argv=sys.argv[1:]; NOATTR='--no-attributes' in argv; argv=[a for a in argv if a!='--no-attributes']
ids=set(open(argv[0]).read().split())
fr_path=argv[1] if len(argv)>1 else shutil.which('git-filter-repo')
if not fr_path: sys.exit('git-filter-repo not found on PATH')
def load(path):
    loader=importlib.machinery.SourceFileLoader('git_filter_repo',path)
    m=importlib.util.module_from_spec(importlib.util.spec_from_loader('git_filter_repo',loader)); loader.exec_module(m); return m
try: fr=load(os.path.realpath(fr_path))   # Homebrew/apt: the command is the whole module
except ImportError: fr=None
if not hasattr(fr,'FilteringOptions'):
    # pip: the command is a stub that imports the module; ask its own interpreter where the module is
    interp=open(fr_path).readline()[2:].strip().split()
    mod=subprocess.run([*interp,'-c','import git_filter_repo,sys; sys.stdout.write(git_filter_repo.__file__)'],
                       capture_output=True,text=True).stdout
    if not mod: sys.exit(f'cannot locate the git_filter_repo module behind {fr_path}')
    fr=load(mod)

gitdir=subprocess.run(['git','rev-parse','--absolute-git-dir'],capture_output=True,text=True).stdout.strip()
lfsdir=os.path.join(gitdir,'lfs','objects')
# bytes git counts as non-printable when it decides whether a file is text (convert.c: gather_stats)
NONPRINTABLE = bytes(c for c in range(32) if c not in (8, 9, 10, 12, 13, 27)) + b'\x7f'
def to_lf(data):   # the rewrite's line-ending fix (lfs_convert.py): CRLF -> LF, or classic-Mac CR -> LF
    # binary by git's own test: a NUL, or more than 1 non-printable byte per 128 printable ones
    nonprintable = len(data) - len(data.translate(None, NONPRINTABLE))
    if b'\0' in data or (len(data) - nonprintable) >> 7 < nonprintable: return data
    if b'\r\n' in data: return data.replace(b'\r\n', b'\n')
    if b'\r' in data and b'\n' not in data: return data.replace(b'\r', b'\n')
    return data
converted_marks=set()   # filter-repo internal blob ids that now hold a pointer
nconv=0; nbytes=0; neol=0

def blob_cb(blob,_meta):
    global nconv,nbytes,neol
    if blob.original_id and blob.original_id.decode() in ids:
        data=blob.data; oid=hashlib.sha256(data).hexdigest()
        d=os.path.join(lfsdir,oid[:2],oid[2:4]); os.makedirs(d,exist_ok=True)
        p=os.path.join(d,oid)
        if not os.path.exists(p):
            with open(p,'wb') as f: f.write(data)
        blob.data=f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(data)}\n".encode()
        converted_marks.add(blob.id); nconv+=1; nbytes+=len(data)
    else:
        lf=to_lf(blob.data)
        if lf!=blob.data: blob.data=lf; neol+=1

state={}   # commit (new filter-repo id) -> frozenset of converted paths in its tree
attr_blob={}  # content -> blob mark
def commit_cb(commit,_meta):
    parent=commit.parents[0] if commit.parents else None
    cur=set(state.get(parent,frozenset()))
    for ch in commit.file_changes:
        if ch.filename==b'.gitattributes': continue
        if ch.type==b'D':
            cur.discard(ch.filename)
        elif ch.type==b'M':
            if ch.blob_id in converted_marks: cur.add(ch.filename)
            else: cur.discard(ch.filename)
        elif ch.type==b'DELETEALL':
            cur=set()
    prev=state.get(parent,frozenset())
    if cur!=prev:
        commit.file_changes=[c for c in commit.file_changes if c.filename!=b'.gitattributes']
        if cur:
            body=b''.join(b'/'+p.replace(b' ',b'[[:space:]]')+b' filter=lfs diff=lfs merge=lfs -text\n' for p in sorted(cur))
            if body not in attr_blob:
                b=fr.Blob(body); filt.insert(b); attr_blob[body]=b.id
            commit.file_changes.append(fr.FileChange(b'M',b'.gitattributes',attr_blob[body],b'100644'))
        else:
            commit.file_changes.append(fr.FileChange(b'D',b'.gitattributes'))
    state[commit.id]=frozenset(cur)

args=fr.FilteringOptions.parse_args(['--force','--prune-empty','never','--prune-degenerate','never'],error_on_empty=False)
filt=fr.RepoFilter(args,blob_callback=blob_cb,commit_callback=None if NOATTR else commit_cb)
filt.run()
print(f"converted {nconv} blob occurrences, {nbytes/1048576:.0f} MB into {lfsdir}; LF line endings in {neol} text blobs")
