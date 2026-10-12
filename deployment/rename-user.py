#!/usr/bin/env python3
"""Rename the single development owner's login without changing its OAuth subject."""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(os.environ.get('AUTH_CONFIG_DIR', '/etc/gpt-plugin-oauth'))
BINARY = os.environ.get('AUTH_BINARY', '/opt/gpt-plugin-oauth/authelia')
SERVICE = os.environ.get('AUTH_SERVICE', 'gpt-plugin-oauth')


def prepare(users, old, new):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.@+\-]{0,319}', new) or new == old:
        raise ValueError('Choose a different lowercase username or email address.')
    if set(users.get('users', {})) != {old} or users['users'][old].get('disabled', False):
        raise ValueError('This development reset requires exactly one enabled account matching --username.')
    users = copy.deepcopy(users)
    account = users['users'].pop(old)
    account['displayname'] = new
    if '@' in new:
        account['email'] = new
    users['users'][new] = account
    return users


def run(*args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('Administration command failed; private command output suppressed.')


def rename_identity(db, old, new):
    if db.execute('SELECT 1 FROM user_opaque_identifier WHERE username = ?', (new,)).fetchone():
        raise ValueError('The new username already has authentication records.')
    rows = db.execute('SELECT identifier FROM user_opaque_identifier WHERE username = ?', (old,)).fetchall()
    if len(rows) != 1:
        raise ValueError('Expected one canonical OAuth subject for this development account.')
    db.execute('UPDATE user_opaque_identifier SET username = ? WHERE username = ?', (new, old))
    return rows[0][0]


def save(path, data):
    info = path.stat()
    fd, name = tempfile.mkstemp(prefix='.rename-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            os.fchmod(target.fileno(), info.st_mode & 0o777)
            os.fchown(target.fileno(), info.st_uid, info.st_gid)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='owner')
    parser.add_argument('--new-username', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run as root via SSH or sudo.')
    os.umask(0o077)
    with open(ROOT / '.password-admin.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = yaml.safe_load((ROOT / 'configuration.yml').read_text())
        paths = [Path(config['authentication_backend']['file']['path'])]
        original = [p.read_text() for p in paths]
        database = Path(config['storage']['local']['path'])
        if not database.is_file():
            raise ValueError('Authentication database is missing.')
        users = prepare(yaml.safe_load(original[0]), args.username, args.new_username)
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
            if db.execute('SELECT 1 FROM user_opaque_identifier WHERE username = ?', (args.new_username,)).fetchone():
                raise ValueError('That username already has authentication records; choose a fresh development username.')
        if args.check:
            print('Ready. Username changes preserve the canonical subject; no changes made.')
            return
        backup_root = Path(os.environ.get('AUTH_BACKUP_DIR', '/var/backups/gpt-plugin-oauth'))
        backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix='rename-', dir=backup_root))
        stopped = False
        modified = False
        try:
            stopped = True
            run('systemctl', 'stop', SERVICE)
            if [p.read_text() for p in paths] != original:
                raise RuntimeError('Configuration changed concurrently; retry.')
            for i, path in enumerate(paths):
                shutil.copy2(path, backup / str(i))
            with sqlite3.connect(database) as source, sqlite3.connect(backup / 'database.sqlite3') as dest:
                source.backup(dest)
            modified = True
            # The user remains the same person; OAuth reconnect validates this stable identity.
            with sqlite3.connect(database) as db:
                subject = rename_identity(db, args.username, args.new_username)
            for path, content in zip(paths, [yaml.safe_dump(users, allow_unicode=True)]):
                save(path, content + '\n')
            run(BINARY, 'validate-config', '--config', str(ROOT / 'configuration.yml'))
            run('systemctl', 'start', SERVICE)
            run('systemctl', 'is-active', '--quiet', SERVICE)
        except BaseException:
            if modified:
                run('systemctl', 'stop', SERVICE)
                for i, path in enumerate(paths):
                    shutil.copy2(backup / str(i), path)
                with sqlite3.connect(backup / 'database.sqlite3') as source, sqlite3.connect(database) as dest:
                    source.backup(dest)
            if stopped:
                run('systemctl', 'start', SERVICE)
            raise
        print('Username changed; password hash and OAuth subject preserved. Reconnect using the new username.')
        print('Second-factor bindings are not migrated. Application configurations are not modified.')
        registration = ROOT / 'account-registration.json'
        registration.write_text(json.dumps({'username': args.new_username, 'subject': subject}))
        print('Register the new subject with each relying application using: ' + str(registration))
        print('Old bootstrap credential files are obsolete. Recovery backup: ' + str(backup))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        sys.exit(str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('Cancelled.')
    except Exception:
        sys.exit('Account reset failed; private details suppressed. Check the root-only recovery backup.')
