#!/usr/bin/env python3
"""Start an isolated loopback instance before replacing the running issuer."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.parse import urlsplit

import yaml


def main():
    binary, prepared = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='auth-smoke-') as directory:
        root = Path(directory)
        config = yaml.safe_load((Path(prepared) / 'configuration.yml').read_text())
        base = urlsplit(config['server']['address']).path.rstrip('/')
        config['server']['address'] = 'tcp://127.0.0.1:19191' + base
        url = 'http://127.0.0.1:19191' + base
        config['notifier']['disable_startup_check'] = True
        users = root / 'users.yml'
        users.write_bytes((Path(prepared) / 'users.yml').read_bytes())
        config['authentication_backend']['file']['path'] = str(users)
        database = root / 'database.sqlite3'
        with sqlite3.connect(config['storage']['local']['path']) as source, sqlite3.connect(database) as target:
            source.backup(target)
        config['storage']['local']['path'] = str(database)
        path = root / 'configuration.yml'
        path.write_text(yaml.safe_dump(config))
        env = {**os.environ, 'AUTH_LOGIN_MODE': 'email_otp', 'AUTH_EMAIL_OTP_STATE': str(root / 'state.json')}
        with (root / 'startup.log').open('w') as log:
            process = subprocess.Popen([binary, '--config', str(path)], env=env, stdout=log, stderr=log)
            try:
                for _ in range(30):
                    if process.poll() is not None:
                        raise RuntimeError('Isolated issuer exited before readiness')
                    try:
                        with urlopen(url + '/api/email-otp/configuration', timeout=2) as response:
                            assert json.load(response)['data']['enabled'] is True
                        with urlopen(url + '/', timeout=2) as response:
                            assert b'<html' in response.read().lower()
                        print('AUTH_ISOLATED_STARTUP_OK')
                        return
                    except OSError:
                        time.sleep(1)
                raise RuntimeError('Isolated issuer readiness timed out')
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
