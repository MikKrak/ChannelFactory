"""Приватный локальный индикатор получателя, без текстов и идентификаторов читателя.

Не источник сообщений/курсора; истинный курсор и захват остаются в Supabase.
Файл обновляется атомарно. Устаревший индикатор не означает разрешение перехвата.
"""
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def state_directory(bot_id):
    if type(bot_id) is not int or bot_id <= 0:
        raise ValueError('Invalid bot ID')
    return Path('/private/tmp') / ('cf-inbox-worker-' + str(bot_id))


def write_state(directory, **values):
    path = Path(directory)
    data = {k: values[k] for k in ('state', 'phase', 'received') if k in values}
    data.update(pid=os.getpid(), updated_at=time.time())
    temporary = path / ('.state-' + str(uuid4()))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path / 'state.json')
    finally:
        temporary.unlink(missing_ok=True)


def read_state(bot_id, directory=None):
    """Читать только свой закрытый файл; пропавший процесс — ошибка, не running."""
    try:
        root = Path(directory) if directory is not None else state_directory(bot_id)
        if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
            return {'state': 'unknown'}
        fd = os.open(root / 'state.json', os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
                return {'state': 'unknown'}
            data = json.loads(stream.read(4096))
        result = {'state': data['state'], 'updated_at': data['updated_at']}
        if result['state'] not in ('running', 'stopped', 'error'):
            return {'state': 'unknown'}
        if result['state'] == 'running':
            if type(data.get('pid')) is not int or data['pid'] <= 0:
                return {'state': 'unknown'}
            try:
                os.kill(data['pid'], 0)
            except ProcessLookupError:
                return {'state': 'error'}
            if time.time() - data['updated_at'] > 90:
                return {'state': 'unknown'}
        return result
    except FileNotFoundError:
        return {'state': 'stopped'}
    except Exception:
        return {'state': 'unknown'}
