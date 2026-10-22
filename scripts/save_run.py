"""Commit what a watch run produced (state.json, log/halftime_log.csv, log/results.csv) on top of whatever is on
main now, and push. .github/workflows/watch.yml runs it after watch.py.

The old step rebased the run's uncommitted files onto main with `git pull --rebase --autostash || true`. When
main had moved under a file the run also changed, the autostash came back with conflict markers inside the
file and the next two lines committed them (30 marker lines in halftime_log.csv after Oct 17, and a state.json
with the pregame lines gone). This script never merges text:
  - the two CSVs are append-only, so the rows this run added (the rows main does not have, by content) are
    appended to main's copy of the file, once each, and a header upgrade widens main's copy instead of
    appending the widened rows again (the Oct 22 results.csv had 50 duplicate rows and two headers in it);
  - state.json is this run's whole snapshot, and a watch run is the only writer of it (one run at a time);
  - a marker line that somehow still turns up is dropped, never committed.
If the push is rejected because main moved again, it starts over from the new main, three times at most.

Usage: python scripts/save_run.py BASE_SHA    (BASE_SHA is the commit the run checked out: github.sha)
"""
import os, re, csv, sys, subprocess, datetime as dt

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


def key(line):
    """A CSV line as the tuple of its fields with trailing blanks dropped, so a row padded to a wider header is the
    same row. Parsed with the csv module, so a quoted comma inside a field does not split it."""
    text = line.decode('utf-8', errors='replace').rstrip('\r\n')
    try:
        fields = next(csv.reader([text]))
    except (csv.Error, StopIteration):
        fields = text.split(',')
    while fields and fields[-1] == '':
        fields.pop()
    return tuple(fields)


def pad(line, n):
    """A CSV line with n empty fields added before its line ending."""
    body = line.rstrip(b'\r\n')
    return body + b',' * n + line[len(body):]


def merge_append(main, base, ours):
    """main's copy of an append-only CSV plus the rows this run added: the rows of ours that neither base nor main
    has, by content, so a row is never on the file twice and a header never lands among the rows. When ours was
    written under a wider header (the results file grew q3 columns), main's header and rows are widened to match,
    the way upgrade_results_csv does it. A file created this run keeps its header only when main has none."""
    if not main:
        return ours
    if not ours or ours == base:
        return main
    ml, ol = lines(main), lines(ours)
    head_m, head_o = key(ml[0]), key(ol[0])
    first = head_m[0] if head_m else None
    have = {key(l) for l in ml} | {key(l) for l in lines(base)}
    have.add(head_o)
    new = []
    for l in ol[1:]:
        k = key(l)
        if not k or k in have or (first is not None and k[0] == first):
            continue
        have.add(k)
        new.append(l)
    if not new:
        return main
    extra = len(head_o) - len(head_m)
    if extra > 0:
        eol = b'\r\n' if ml[0].endswith(b'\r\n') else b'\n'
        ml = [ol[0].rstrip(b'\r\n') + eol] + [pad(l, extra) for l in ml[1:]]
        main = b''.join(ml)
    if not main.endswith(b'\n'):
        main += b'\r\n' if b'\r\n' in main else b'\n'
    return main + b''.join(new)


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
