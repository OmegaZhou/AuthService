#!/usr/bin/env python3
"""Prepare independent authentication configuration from administrator inputs.

Reads SMTP credentials once during provisioning, never at service runtime.
Does not read or modify any relying application's configuration.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import uuid

from argon2 import PasswordHasher
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--smtp-env', required=True)
    parser.add_argument('--recipient-json', required=True)
    parser.add_argument('--users-path', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--group', default='plugin-users')
    args = parser.parse_args()
    os.umask(0o077)
    out = Path(args.output)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    smtp = {}
    for line in Path(args.smtp_env).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            name, value = line.split('=', 1)
            values = shlex.split(value)
            if values:
                smtp[name.strip()] = values[0]
    recipient = json.loads(Path(args.recipient_json).read_text())['email'].strip().lower()
    if '@' not in recipient or any(c in recipient for c in '\r\n\0'):
        raise ValueError('Invalid recipient')
    config = yaml.safe_load(Path(args.config).read_text())
    config['authentication_backend']['file']['path'] = args.users_path
    config['authentication_backend']['password_reset'] = {'disable': True}
    config['authentication_backend']['password_change'] = {'disable': True}
    config['webauthn'] = {**config.get('webauthn', {}), 'enable_passkey_login': False}
    for client in config['identity_providers']['oidc']['clients']:
        if 'email' not in client['scopes']:
            client['scopes'].append('email')
    port = int(smtp['SMTP_PORT'])
    config['notifier'] = {'smtp': {
        'address': ('submissions' if port == 465 else 'submission') + '://' + smtp['SMTP_HOST'] + ':' + str(port),
        'username': smtp['SMTP_USERNAME'],
        'password': Path(smtp['SMTP_PASSWORD_FILE']).read_text().strip(),
        'sender': smtp['MAIL_FROM'], 'startup_check_address': recipient,
        'subject': '[Account login] {title}', 'timeout': '15 seconds',
    }}
    users = {'users': {recipient: {'displayname': recipient, 'email': recipient, 'groups': [args.group],
                                  'password': PasswordHasher().hash(secrets.token_urlsafe(48))}}}
    registration = {'username': recipient, 'subject': str(uuid.uuid4())}
    (out / 'configuration.yml').write_text(yaml.safe_dump(config))
    (out / 'users.yml').write_text(yaml.safe_dump(users))
    (out / 'registration.json').write_text(json.dumps(registration))
    print('Independent authentication configuration prepared; no running service changed.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Preparation failed; private details suppressed.')
