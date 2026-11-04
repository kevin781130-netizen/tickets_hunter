"""Credential storage: OS secret stores only, never a file/env/argv/log."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import ncl_openlab_credentials as cred

SECRET = "pw-Sup3r-secret-!"
ACCOUNT = "A123456789"


class MemoryBackend:
    """Duck-typed stand-in for the OS keychain."""

    def __init__(self):
        self.items = {}

    def set_password(self, service, user, password):
        self.items[(service, user)] = password

    def get_password(self, service, user):
        return self.items.get((service, user))

    def delete_password(self, service, user):
        if (service, user) not in self.items:
            raise KeyError(user)
        del self.items[(service, user)]


class FailLikeBackend(MemoryBackend):
    __module__ = "keyring.backends.fail"


class PlaintextLikeBackend(MemoryBackend):
    __module__ = "keyrings.alt.file"


class ChainLikeBackend(MemoryBackend):
    def __init__(self, *inner):
        super().__init__()
        self.backends = list(inner)


class StoreTests(unittest.TestCase):
    def test_save_load_describe_delete(self):
        backend = MemoryBackend()
        store = cred.CredentialStore(backend)
        self.assertEqual(store.describe(), "尚未儲存憑證")
        store.save(ACCOUNT, SECRET)
        self.assertEqual(store.load(), (ACCOUNT, SECRET))
        self.assertEqual(store.account(), ACCOUNT)
        self.assertTrue(store.has_saved())
        self.assertEqual(store.describe(), "已安全儲存：A1****89")
        self.assertNotIn(SECRET, store.describe())
        store.delete()
        self.assertIsNone(store.load())
        self.assertFalse(store.has_saved())
        self.assertEqual(backend.items, {})
        store.delete()      # idempotent

    def test_a_new_save_replaces_the_pointer(self):
        store = cred.CredentialStore(MemoryBackend())
        store.save("OLD1234567", "x1")
        store.save(ACCOUNT, SECRET)
        self.assertEqual(store.load(), (ACCOUNT, SECRET))

    def test_bad_input_is_refused_without_echoing_it(self):
        store = cred.CredentialStore(MemoryBackend())
        for account, password in (("", SECRET), ("   ", SECRET), (ACCOUNT, ""), (ACCOUNT, "x" * 500),
                                  (ACCOUNT, "a\nb"), (None, SECRET), (ACCOUNT, None)):
            with self.assertRaises(cred.CredentialError) as ctx:
                store.save(account, password)
            self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIsNone(store.load())

    def test_insecure_backends_are_refused(self):
        for backend in (FailLikeBackend(), PlaintextLikeBackend(),
                        ChainLikeBackend(MemoryBackend(), PlaintextLikeBackend())):
            store = cred.CredentialStore(backend)
            self.assertFalse(store.is_secure(), type(backend).__name__)
            with self.assertRaises(cred.CredentialError):
                store.save(ACCOUNT, SECRET)
            self.assertEqual(backend.items, {})
            self.assertIn("沒有安全金鑰庫", store.describe())
        self.assertTrue(cred.CredentialStore(ChainLikeBackend(MemoryBackend())).is_secure())

    def test_backend_errors_become_safe_messages(self):
        class Broken(MemoryBackend):
            def set_password(self, *a):
                raise RuntimeError(f"boom {SECRET}")
        with self.assertRaises(cred.CredentialError) as ctx:
            cred.CredentialStore(Broken()).save(ACCOUNT, SECRET)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIsNone(cred.CredentialStore(Broken()).load())

    def test_mask(self):
        self.assertEqual(cred.mask_account("A123456789"), "A1****89")
        self.assertEqual(cred.mask_account("123"), "****")
        self.assertEqual(cred.mask_account(None), "****")

    def test_nothing_is_written_to_disk_env_or_argv(self):
        before_env = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                store = cred.CredentialStore(MemoryBackend())
                store.save(ACCOUNT, SECRET)
                store.load()
                store.describe()
                self.assertEqual(list(Path(tmp).rglob("*")), [])
            finally:
                os.chdir(cwd)
        self.assertEqual(dict(os.environ), before_env)
        self.assertFalse(any(SECRET in arg for arg in sys.argv))

    def test_source_never_prints_or_logs_secrets(self):
        text = (HERE.parent / "src" / "ncl_openlab_credentials.py").read_text(encoding="utf-8")
        for forbidden in ("print(", "logging", "os.environ", "subprocess", "open(", "write_text"):
            self.assertNotIn(forbidden, text, forbidden)


try:
    import keyring
    from keyring.backend import KeyringBackend
    HAVE_KEYRING = True
except ImportError:
    HAVE_KEYRING = False


@unittest.skipUnless(HAVE_KEYRING, "NOT_RUN: keyring package is not installed")
class RealKeyringLibraryTests(unittest.TestCase):
    """The real keyring API with an in-memory backend (no OS keychain is touched)."""

    def setUp(self):
        class Mem(KeyringBackend):
            priority = 5
            store = {}

            def set_password(self, service, username, password):
                self.store[(service, username)] = password

            def get_password(self, service, username):
                return self.store.get((service, username))

            def delete_password(self, service, username):
                self.store.pop((service, username), None)
        self.previous = keyring.get_keyring()
        keyring.set_keyring(Mem())
        self.addCleanup(lambda: keyring.set_keyring(self.previous))

    def test_default_path_uses_the_keyring_package(self):
        store = cred.CredentialStore()
        self.assertTrue(store.is_secure())
        store.save(ACCOUNT, SECRET)
        self.assertEqual(store.load(), (ACCOUNT, SECRET))
        store.delete()
        self.assertIsNone(store.load())

    def test_the_machines_default_backend_is_checked_not_assumed(self):
        keyring.set_keyring(self.previous)       # whatever this machine has (often 'fail' in CI)
        store = cred.CredentialStore()
        secure = store.is_secure()
        self.assertEqual(secure, "fail" not in type(keyring.get_keyring()).__module__
                         and "null" not in type(keyring.get_keyring()).__module__)
        if not secure:
            with self.assertRaises(cred.CredentialError):
                store.save(ACCOUNT, SECRET)


if __name__ == "__main__":
    unittest.main()
