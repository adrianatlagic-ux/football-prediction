"""Small, atomic runtime JSON files, stored under data/jobs on the Fly volume."""
import json
import os
from pathlib import Path
import tempfile
import threading

_lock = threading.Lock()


def read(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write(path, data):
    path = Path(path)
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = stream.name
            json.dump(data, stream)
        os.replace(temp, path)
        return True
    except OSError:
        return False
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def note_quota(path, headers, observed_at):
    values = {}
    for name, header in [('remaining_credits', 'x-requests-remaining'),
                         ('used_credits', 'x-requests-used'),
                         ('last_request_credits', 'x-requests-last')]:
        try:
            value = int(headers.get(header))
            values[name] = value if value >= 0 else None
        except (AttributeError, TypeError, ValueError):
            values[name] = None
    if all(v is None for v in values.values()):
        return
    with _lock:
        previous = read(path)
        values['observed_at'] = observed_at
        if values['last_request_credits'] is not None and values['last_request_credits'] > 0:
            values['last_paid_request'] = {'credits': values['last_request_credits'], 'observed_at': observed_at}
        elif previous.get('last_paid_request'):
            values['last_paid_request'] = previous['last_paid_request']
        write(path, values)
