import copy
import importlib.util
from pathlib import Path
import unittest
import sqlite3

spec = importlib.util.spec_from_file_location('rename_admin', Path(__file__).with_name('rename-user.py'))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class RenameTests(unittest.TestCase):
    def setUp(self):
        self.users = {'users': {'owner': {'password': 'hash', 'groups': ['gptmail'], 'displayname': 'old'}}}

    def test_email_username_keeps_password_without_application_configuration(self):
        users = admin.prepare(self.users, 'owner', 'test@example.com')
        self.assertEqual(set(users['users']), {'test@example.com'})
        self.assertEqual(users['users']['test@example.com']['password'], 'hash')
        self.assertEqual(users['users']['test@example.com']['email'], 'test@example.com')
        self.assertEqual(set(self.users['users']), {'owner'})

    def test_reject_invalid_names_and_multiple_owners(self):
        for name in ['owner', '../user', 'x;id', '', 'UPPER']:
            with self.assertRaises(ValueError):
                admin.prepare(self.users, 'owner', name)
        self.users['users']['another'] = {'password': 'hash'}
        with self.assertRaises(ValueError):
            admin.prepare(self.users, 'owner', 'new-owner')

    def test_rename_preserves_subject_and_rejects_existing_identity(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE user_opaque_identifier (username TEXT, identifier TEXT)')
            db.execute('INSERT INTO user_opaque_identifier VALUES (?, ?)', ('owner', 'stable-subject'))
            subject = admin.rename_identity(db, 'owner', 'test@example.com')
            self.assertEqual(subject, 'stable-subject')
            self.assertEqual(db.execute('SELECT * FROM user_opaque_identifier').fetchall(), [('test@example.com', 'stable-subject')])
            db.execute('INSERT INTO user_opaque_identifier VALUES (?, ?)', ('other', 'other-subject'))
            with self.assertRaises(ValueError):
                admin.rename_identity(db, 'test@example.com', 'other')


if __name__ == '__main__':
    unittest.main()
