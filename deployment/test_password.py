import importlib.util
from pathlib import Path
import tempfile
import unittest

from argon2 import PasswordHasher
import yaml

spec = importlib.util.spec_from_file_location('password_admin', Path(__file__).with_name('change-password.py'))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class PasswordTests(unittest.TestCase):
    def test_replace_preserves_identity_and_other_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'users.yml'
            original = {'users': {'owner': {'password': 'old-hash', 'groups': ['gptmail'],
                        'displayname': 'Owner', 'email': 'test@example.com'},
                        'other': {'password': 'unchanged', 'disabled': True}}}
            path.write_text(yaml.safe_dump(original))
            path.chmod(0o640)
            admin.replace_password(path, 'owner', 'fixture-password-only-1234')
            updated = yaml.safe_load(path.read_text())
            digest = updated['users']['owner']['password']
            self.assertTrue(digest.startswith('$argon2id$'))
            self.assertTrue(PasswordHasher().verify(digest, 'fixture-password-only-1234'))
            updated['users']['owner']['password'] = 'old-hash'
            self.assertEqual(original, updated)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            saved = path.read_bytes()
            for username, password in [('owner', 'short'), ('missing', 'long-enough-password'),
                                       ('other', 'long-enough-password')]:
                with self.assertRaises(ValueError):
                    admin.replace_password(path, username, password)
                self.assertEqual(path.read_bytes(), saved)
            self.assertNotIn(b'fixture-password-only-1234', saved)


if __name__ == '__main__':
    unittest.main()
