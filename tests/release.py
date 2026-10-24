"""Pins what moves the worker branch (.github/workflows/release.yml), which Railway deploys from (Oct 24).
1. Every local module worker.py imports, directly or through another module, and every repo JSON they read
   (config.json, model.json) is covered by release.yml's paths, so a change to what the worker runs always
   reaches it. state.json is the exception on purpose: the worker's state lives in Supabase.
2. Nothing the backup, the export or the app writes matches those paths (state.json, log/, data/, app/,
   scripts/, tests/), so a state save or an app change never rebuilds or restarts the worker.
3. Only release.yml moves the worker branch, the backup still pushes to main, the tests gate the release, and
   the run fails when Railway never shows up on the moved commit."""
import ast, json, os, re, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, '.github', 'workflows')
release = open(os.path.join(WF, 'release.yml')).read()


def paths_of(text):
    """The list under on: push: paths: (two-space YAML, as the workflows are written)."""
    lines, out, inside, indent = text.splitlines(), [], False, None
    for ln in lines:
        if re.match(r'^\s+paths:\s*$', ln):
            inside, indent = True, None
            continue
        if inside:
            m = re.match(r'^(\s+)-\s+(.+?)\s*$', ln)
            if m and (indent is None or len(m.group(1)) == indent):
                indent = len(m.group(1))
                out.append(m.group(2).strip('\'"'))
                continue
            break
    return out


def glob_re(pat):
    """GitHub's filter glob: ** crosses folders, * and ? do not, the pattern is matched against the whole path."""
    i, rx = 0, ''
    while i < len(pat):
        if pat.startswith('**', i):
            rx += '.*'
            i += 2
            if pat.startswith('/', i):
                i += 1
                rx = rx[:-2] + '(?:.*/)?'
        elif pat[i] == '*':
            rx += '[^/]*'
            i += 1
        elif pat[i] == '?':
            rx += '[^/]'
            i += 1
        else:
            rx += re.escape(pat[i])
            i += 1
    return re.compile(rx + r'\Z')


PATHS = paths_of(release)
assert PATHS, 'release.yml has no push paths'
RX = [glob_re(p) for p in PATHS]


def covered(rel):
    return any(r.match(rel) for r in RX)


# 1. the worker's import closure and the repo files it reads
start = json.load(open(os.path.join(ROOT, 'railway.json')))['deploy']['startCommand']
entry = re.search(r'(\S+\.py)', start).group(1)
assert '/' not in entry, f'railway.json starts {entry}; release.yml assumes the entry point sits at the repo root'


def local_module(name):
    for rel in (f'{name}.py', os.path.join(name, '__init__.py')):
        if os.path.exists(os.path.join(ROOT, rel)):
            return rel
    return None


seen, todo = set(), [entry]
while todo:
    rel = todo.pop()
    if rel in seen:
        continue
    seen.add(rel)
    tree = ast.parse(open(os.path.join(ROOT, rel)).read(), filename=rel)
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
        for n in names:
            m = local_module(n.split('.')[0])
            if m:
                todo.append(m)
for rel in sorted(seen):
    assert covered(rel), f'the worker imports {rel}, which release.yml paths do not cover: a change there would never deploy'

src = ''.join(open(os.path.join(ROOT, rel)).read() for rel in seen)
named = {f for f in re.findall(r"['\"]([\w.-]+\.json)['\"]", src) if os.path.exists(os.path.join(ROOT, f))}
for f in sorted(named - {'state.json'}):
    assert covered(f), f'the worker reads {f}, which release.yml paths do not cover'
assert {'config.json', 'model.json'} <= named, f'expected the worker to read config.json and model.json, found {sorted(named)}'
for f in ('requirements.txt', '.python-version', 'railway.json'):
    assert covered(f), f'{f} changes how Railway builds the worker; release.yml paths must cover it'
print(f"release: the worker's {len(seen)} modules ({', '.join(sorted(seen))}) and config.json, model.json move the worker branch")

# 2. what the backup, the export and the app write never does
for rel in ('state.json', 'log/halftime_log.csv', 'log/results.csv', 'data/desk/games/2026-10-23.csv.gz',
            'data/desk/quote_snapshots/2026-10-23.csv.gz', 'data/cfb_games.csv', 'app/app/page.jsx',
            'app/preview/shots.py', 'app/vercel.json', 'scripts/save_run.py', 'scripts/export_desk.py',
            'tests/parity.py', 'supabase/013_app_auto.sql', 'README.md', 'claude/notes.md',
            '.github/workflows/watch.yml', '.github/workflows/test.yml'):
    assert not covered(rel), f'{rel} matches release.yml paths: a save or an app change would rebuild the worker'
print('release: state saves, logs, the data export, app, scripts, tests and docs never move it')

# 3. who may move the branch, and the gate in front of it
assert re.search(r'^on:\s*\n\s+push:\s*\n\s+branches:\s*\[main\]', release, re.M), 'release.yml must run on pushes to main'
assert re.search(r'uses:\s*\./\.github/workflows/test\.yml', release) and re.search(r'needs:\s*tests', release), \
    'release.yml must run the tests and move the branch only after they pass'
assert 'force=false' in release, 'release.yml must move the branch fast-forward only'
assert 'railway-app[bot]' in release and 'exit 1' in release.split('Check Railway picked it up', 1)[-1], \
    'release.yml must fail when Railway never shows up on the moved commit (a silent non-deploy)'
assert 'workflow_call' in open(os.path.join(WF, 'test.yml')).read(), 'test.yml must be callable by release.yml'
for path in glob.glob(os.path.join(WF, '*.yml')) + glob.glob(os.path.join(ROOT, 'scripts', '*.py')):
    if os.path.basename(path) == 'release.yml':
        continue
    text = open(path).read()
    assert not re.search(r'heads/worker|HEAD:worker|:worker\b', text), f'{os.path.relpath(path, ROOT)} names the worker branch; only release.yml moves it'
assert "'HEAD:main'" in open(os.path.join(ROOT, 'scripts', 'save_run.py')).read(), 'the backup must keep pushing its saves to main'
print('release: only release.yml moves worker, after the tests pass, fast-forward only, and fails if Railway never sees it; the backup pushes to main')
print('release: ok')
