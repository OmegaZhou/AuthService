#!/usr/bin/env python3
"""Root-only, interactive password reset for the existing Authelia file account."""
import argparse
import fcntl
import getpass
import os
from pathlib import Path
import stat
import sys
import tempfile

from argon2 import PasswordHasher, Type
import yaml

ROOT = Path(os.environ.get('AUTH_CONFIG_DIR', '/etc/gpt-plugin-oauth'))


def replace_password(path, username, password):
    if len(password) < 12 or len(password) > 1024 or any(c in password for c in '\r\n\0'):
        raise ValueError('Use 12–1024 characters without line breaks.')
    original = path.read_bytes()
    info = path.stat()
    data = yaml.safe_load(original)
    account = data['users'].get(username)
    if not isinstance(account, dict) or account.get('disabled', False):
        raise ValueError('An enabled account with that username is required.')
    hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                            hash_len=32, salt_len=16, type=Type.ID)
    digest = hasher.hash(password)
    hasher.verify(digest, password)
    account['password'] = digest
    encoded = yaml.safe_dump(data, allow_unicode=True).encode('utf-8')
    # Preserve all identities, groups and other accounts; replace the file atomically.
    fd, name = tempfile.mkstemp(prefix='.users-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            os.fchmod(target.fileno(), stat.S_IMODE(info.st_mode))
            os.fchown(target.fileno(), info.st_uid, info.st_gid)
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        if path.read_bytes() != original:
            raise RuntimeError('Account file changed concurrently; no update made. Retry.')
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='owner', help='Existing account; does not rename it')
    parser.add_argument('--check', action='store_true', help='Check readiness without changing a password')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run as root via SSH or sudo.')
    os.umask(0o077)
    with open(ROOT / '.password-admin.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = yaml.safe_load((ROOT / 'configuration.yml').read_text())
        backend = config['authentication_backend']['file']
        users_path = Path(backend['path'])
        data = yaml.safe_load(users_path.read_text())
        account = data['users'].get(args.username)
        if not account or account.get('disabled', False):
            raise ValueError('Enabled account not found.')
        if not backend.get('watch', False):
            raise ValueError('Expected watched file backend is not configured.')
        if args.check:
            print('Ready: enabled account, watched backend, Argon2id available. No changes made.')
            return
        if not sys.stdin.isatty():
            raise ValueError('Use an interactive terminal (ssh -t).')
        password = getpass.getpass('New password (12+ characters): ')
        if password != getpass.getpass('Confirm new password: '):
            raise ValueError('Passwords do not match. No changes made.')
        replace_password(users_path, args.username, password)
        print('Password updated. Authelia watches this file; no restart is needed.')
        print('Previously issued OAuth tokens are not revoked by this password reset.')
        print('Previously saved bootstrap password files are now obsolete; the new password was not saved in plaintext.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        sys.exit(str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('Cancelled.')
    except Exception:
        sys.exit('Password update failed. Inspect account file permissions and dependencies; private details suppressed.')
