# -*- coding: utf-8 -*-
"""Library-card credentials in the operating system's secret store.

macOS: Keychain. Windows: Credential Manager. (Linux: Secret Service / KWallet.)
All through the ``keyring`` package, so a password never appears in a file, an
environment variable, a command line or a log. Backends that would keep it in
plain text, or that do nothing, are refused.

Nothing here logs, prints or returns a password except load(), which hands it to
the caller in memory for the moment of typing it into the official login form.
"""
SERVICE = "ncl-openlab"
POINTER = "__account__"
MAX_LEN = 128
_INSECURE_MARKERS = (".fail", ".null", "keyrings.alt", "plaintext")


class CredentialError(RuntimeError):
    """Stable, user-readable reasons (never contains the secret)."""


def _backend_names(backend):
    """Class paths of a backend, looking inside chainers."""
    inner = getattr(backend, "backends", None)
    if inner:
        return [n for b in inner for n in _backend_names(b)]
    return [f"{type(backend).__module__}.{type(backend).__name__}".lower()]


def mask_account(account):
    """'A123456789' -> 'A1****89'. Short values are fully masked."""
    text = str(account or "")
    return text[:2] + "****" + text[-2:] if len(text) >= 6 else "****"


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend

    def _kr(self):
        if self._backend is not None:
            return self._backend
        try:
            import keyring
        except ImportError:
            raise CredentialError("尚未安裝 keyring，無法安全儲存憑證（pip install keyring）") from None
        return keyring

    def _active(self):
        kr = self._kr()
        return kr.get_keyring() if hasattr(kr, "get_keyring") else kr

    def backend_name(self):
        try:
            return type(self._active()).__name__
        except CredentialError:
            return "unavailable"

    def is_secure(self):
        names = _backend_names(self._active())
        return bool(names) and not any(m in n for n in names for m in _INSECURE_MARKERS)

    def _require_secure(self):
        if not self.is_secure():
            raise CredentialError("這台電腦沒有可用的安全金鑰庫（Keychain／Credential Manager），不會儲存憑證")

    @staticmethod
    def _clean(value, label):
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_LEN or \
                any(ord(c) < 32 for c in value):
            raise CredentialError(f"{label}不可為空白、過長或含控制字元")
        return value

    def save(self, account, password):
        account = self._clean(account, "閱覽證號").strip()
        self._clean(password, "密碼")
        self._require_secure()
        kr = self._kr()
        try:
            kr.set_password(SERVICE, account, password)
            kr.set_password(SERVICE, POINTER, account)
        except Exception as exc:
            raise CredentialError(f"寫入金鑰庫失敗（{type(exc).__name__}）") from None

    def account(self):
        """The stored account id (not the password), or None."""
        try:
            return self._kr().get_password(SERVICE, POINTER) or None
        except CredentialError:
            return None
        except Exception:
            return None

    def has_saved(self):
        account = self.account()
        if not account:
            return False
        try:
            return bool(self._kr().get_password(SERVICE, account))
        except Exception:
            return False

    def load(self):
        """(account, password) for the moment of typing, or None. Never log the result."""
        account = self.account()
        if not account:
            return None
        try:
            password = self._kr().get_password(SERVICE, account)
        except Exception:
            return None
        return (account, password) if password else None

    def delete(self):
        account = self.account()
        kr = self._kr()
        for name in ([account] if account else []) + [POINTER]:
            try:
                kr.delete_password(SERVICE, name)
            except Exception:
                pass  # already gone

    def describe(self):
        """One-line status for the GUI: never includes the password."""
        try:
            if not self.is_secure():
                return "此電腦沒有安全金鑰庫，無法儲存憑證（仍可手動登入）"
        except CredentialError as exc:
            return str(exc)
        account = self.account()
        if account and self.has_saved():
            return f"已安全儲存：{mask_account(account)}"
        return "尚未儲存憑證"
