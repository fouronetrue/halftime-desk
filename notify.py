"""Push notifications. ntfy.sh by default (free, no account: install the ntfy app and subscribe to your topic).
Set NTFY_TOPIC in the environment (GitHub Actions secret). Optional PUSHOVER_TOKEN + PUSHOVER_USER for Pushover."""
import os

try:
    import requests
except ImportError:
    requests = None


def push(title, body, priority='default', tags='football'):
    sent = []
    topic = os.environ.get('NTFY_TOPIC')
    if topic and requests:
        try:
            r = requests.post(f'https://ntfy.sh/{topic}', data=body.encode('utf-8'),
                              headers={'Title': title, 'Priority': priority, 'Tags': tags}, timeout=15)
            sent.append(f'ntfy {r.status_code}')
        except Exception as e:
            sent.append(f'ntfy failed: {e}')
    tok, usr = os.environ.get('PUSHOVER_TOKEN'), os.environ.get('PUSHOVER_USER')
    if tok and usr and requests:
        try:
            r = requests.post('https://api.pushover.net/1/messages.json', data=dict(token=tok, user=usr, title=title, message=body,
                              priority=1 if priority == 'high' else 0), timeout=15)
            sent.append(f'pushover {r.status_code}')
        except Exception as e:
            sent.append(f'pushover failed: {e}')
    if not sent:
        sent.append('no push channel configured (printed only)')
    print(f'[push {priority}] {title}\n{body}\n  -> {", ".join(sent)}')
    return sent
