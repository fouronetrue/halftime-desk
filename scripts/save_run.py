"""Commit what a watch run produced (state.json, log/halftime_log.csv, log/results.csv) on top of whatever is on
main now, and push. .github/workflows/watch.yml runs it after watch.py.

The old step rebased the run's uncommitted files onto main with `git pull --rebase --autostash || true`. When
main had moved under a file the run also changed, the autostash came back with conflict markers inside the
file and the next two lines committed them (30 marker lines in halftime_log.csv after Oct 17, and a state.json
with the pregame lines gone). This script never merges text:
  - the two CSVs are append-only, so the rows this run added (everything past the version it checked out)
    are appended to main's copy of the file;
  - state.json is this run's whole snapshot, and a watch run is the only writer of it (one run at a time);
  - a marker line that somehow still turns up is dropped, never committed.
If the push is rejected because main moved again, it starts over from the new main, three times at most.

Usage: python scripts/save_run.py BASE_SHA    (BASE_SHA is the commit the run checked out: github.sha)
"""
import os, re, sys, subprocess, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = ['state.json']
APPEND = ['log/halftime_log.csv', 'log/results.csv']
MARKER = re.compile(rb'^(<<<<<<< |=======\r?$|>>>>>>> )')


def git(*args, check=True):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r


def show(ref, path):
    """Bytes of a file at a commit, b'' when it does not exist there. Bytes, so CRLF rows stay as written."""
    r = git('show', f'{ref}:{path}', check=False)
    return r.stdout if r.returncode == 0 else b''


def read(path):
    p = os.path.join(ROOT, path)
    return open(p, 'rb').read() if os.path.exists(p) else b''


def write(path, data):
    p = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(data)


def lines(data):
    return data.splitlines(keepends=True)


def added_rows(base, ours):
    """What this run appended: ours past the base it started from. If base is somehow not a prefix of ours,
    the rows of ours that base does not have, in order."""
    if ours.startswith(base):
        return ours[len(base):]
    seen = set(lines(base))
    return b''.join(l for l in lines(ours) if l not in seen)


def merge_append(main, base, ours):
    """main's copy of an append-only CSV plus the rows this run added. A file created this run keeps its header
    only when main has none."""
    new = added_rows(base, ours)
    if not main:
        return ours
    if not new:
        return main
    head = lines(ours)[0] if ours else b''
    if head and new.startswith(head) and main.startswith(head):
        new = new[len(head):]
    if not main.endswith(b'\n'):
        main += b'\r\n' if b'\r\n' in main else b'\n'
    return main + new


def strip_markers(path, data):
    kept = [l for l in lines(data) if not MARKER.match(l)]
    dropped = len(lines(data)) - len(kept)
    if dropped:
        print(f'{path}: dropped {dropped} conflict marker lines')
    return b''.join(kept)


def main(base):
    ours = {p: read(p) for p in SNAPSHOT + APPEND}
    before = {p: show(base, p) for p in APPEND}
    for attempt in range(3):
        git('fetch', '-q', 'origin', 'main')
        git('reset', '-q', '--hard', 'origin/main')
        changed = []
        for p in SNAPSHOT:
            if ours[p]:
                write(p, ours[p])
                changed.append(p)
        for p in APPEND:
            if ours[p]:
                # main's copy comes from the commit, not the working tree: a file this run created is untracked
                # there and would survive the reset, and its rows would be appended to themselves.
                write(p, strip_markers(p, merge_append(show('origin/main', p), before[p], ours[p])))
                changed.append(p)
        if not changed:
            print('nothing to save')
            return
        git('add', '--', *changed)
        if git('diff', '--cached', '--quiet', check=False).returncode == 0:
            print('nothing new to save')
            return
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        git('commit', '-q', '-m', f'state {stamp}')
        r = git('push', '-q', 'origin', 'HEAD:main', check=False)
        if r.returncode == 0:
            print(f'saved {", ".join(changed)} as state {stamp}')
            return
        print(f"push rejected ({r.stderr.decode(errors='replace').strip()[:160]}), starting over from the new main")
    sys.exit('could not push the run after three tries')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
