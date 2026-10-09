"""Pre-flight check for the rewrite: finds what would stop the build, or be left out, in a few seconds.

Usage:
    python3 -I preflight.py <source.git> [<github clone.git>]

<source.git> is the build input (README step 4); with the GitHub clone it also lists refs that step 4 leaves out.
Reads SKIP from build_fp.py and DROP from carry_refs.py, so it always matches what the build will do.

STOP   the build would fail: fix before running pipeline_fp.sh (exit code 1)
DROP   left out of the new history on purpose or by the rules; check that's intended
NOTE   worth knowing, no action needed by the build
"""
import ast, os, re, subprocess as sp, sys

SRC = sys.argv[1]; CLONE = sys.argv[2] if len(sys.argv) > 2 else None
HERE = os.path.dirname(os.path.abspath(__file__))

def git(repo, *a):
    return sp.run(['git', '-C', repo, *a], capture_output=True, text=True).stdout.strip()

def literal(script, name):   # a top-level `NAME = {...}` in one of the build scripts
    for node in ast.parse(open(os.path.join(HERE, script)).read()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    sys.exit(f'{name} not found in {script}')

SKIP = literal('build_fp.py', 'SKIP'); DROP = literal('carry_refs.py', 'DROP')
stops = []
def stop(msg): stops.append(msg); print('STOP  ' + msg)

heads = git(SRC, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/').split()
if 'main' not in heads: sys.exit('STOP  no main branch in ' + SRC)
if 'master' in heads: stop('master is in the source repo; README step 4 removes it')

# ---- releases: each one's first-parent line back to main's first-parent line must have no merges
mainfp = set(git(SRC, 'rev-list', '--first-parent', 'main').split())
releases = sorted(b for b in heads if b.startswith('release-'))
print(f'releases: {len(releases)} ({releases[0] if releases else "-"} .. {releases[-1] if releases else "-"})')
for r in releases:
    if not re.fullmatch(r'release-\d+', r):
        stop(f'{r}: every release-* branch is built as a release, but this name is not release-NNNN; rename or delete it')
        continue
    if r in SKIP: print(f'DROP  {r}: in SKIP (build_fp.py)'); continue
    n = 0
    for line in git(SRC, 'rev-list', '--first-parent', '--parents', r).splitlines():
        c, *parents = line.split()
        if c in mainfp: break
        n += 1
        if len(parents) > 1: stop(f'{r}: merge {c[:10]} on its own line (build_fp.py does not handle it)'); break
        if n > 500: stop(f'{r}: no cut point on main within 500 commits'); break

# ---- releases still deployed or not yet deployed must stay branches at cutover
vtags = set(git(SRC, 'for-each-ref', '--format=%(refname:short)', 'refs/tags/v[0-9]*').split())
for r in releases[-3:]:
    num = r.split('-')[-1]; date = git(SRC, 'log', '-1', '--format=%cs', r)
    deployed = f'v{num}' in vtags
    print(f'NOTE  {r}: last commit {date}, ' + (f'has v{num} (GitHub Release)' if deployed else f'no v{num} tag yet (not deployed?)'))
print('NOTE  the release in production and any not yet deployed must be turned back into release-NNNN branches '
      'before the push (HANDOVER section 5, item 6)')

# ---- feature branches: carried unless DROP; a merge inside one stops carry_refs.py
carried = [b for b in heads if b not in ('main', 'master') and not b.startswith('release-') and b not in DROP]
print(f'feature branches: {len(carried)} carried, {len([b for b in heads if b in DROP])} dropped (DROP)')
for b in carried:
    base = git(SRC, 'merge-base', 'main', b)
    count = git(SRC, 'rev-list', '--count', f'{base}..{b}')
    merges = git(SRC, 'rev-list', '--merges', f'{base}..{b}').split()
    date = git(SRC, 'log', '-1', '--format=%cs', b)
    if merges:
        stop(f'{b}: {len(merges)} merge commit(s) on the branch (e.g. {merges[0][:10]}); carry_refs.py does not handle '
             'them. Rebase it, or add it to DROP and move it afterwards with remap-branch.sh')
    else:
        print(f'carry {b:34} {count:>4} commit(s), last {date}')

# ---- v tags: carried; one whose files match no new commit gets a snapshot commit
for t in sorted(vtags):
    c = git(SRC, 'rev-parse', t + '^{commit}')
    on = git(SRC, 'for-each-ref', '--contains', c, '--format=%(refname:short)', 'refs/heads/main', 'refs/heads/release-*')
    if not on: print(f'NOTE  {t}: its commit is not on main or a release; it will get a one-commit snapshot')
print(f'v tags: {len(vtags)} carried')

# ---- refs in the GitHub clone that the source repo leaves out
if CLONE:
    tags = git(CLONE, 'for-each-ref', '--format=%(refname:short)', 'refs/tags/').split()
    for t in tags:
        if t.startswith('archive/release-'):
            name = t[len('archive/'):]
            if name in heads and git(CLONE, 'rev-parse', t + '^{commit}') != git(SRC, 'rev-parse', name):
                print(f'NOTE  {t} and branch {name} point at different commits; the tag wins (README step 4)')
        elif not re.fullmatch(r'v[0-9].*', t):
            print(f'DROP  tag {t}: only v* and archive/release-* tags are kept')
    clone_heads = set(git(CLONE, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/').split())
    for b in sorted(clone_heads - set(heads) - {'master'}):
        print(f'DROP  branch {b}: in the clone but not in the source repo')

print(f'\n{len(stops)} problem(s) that would stop the build' if stops else '\nok: nothing would stop the build')
sys.exit(1 if stops else 0)
