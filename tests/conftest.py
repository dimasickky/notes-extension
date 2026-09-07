"""Shared pytest fixtures for notes tests."""
import os

os.environ.setdefault("NOTES_API_URL", "http://localhost:8000")

import imperal_sdk.testing as _testing_mod
from imperal_sdk.testing import MockContext as _RealMockContext, MockSecretStore


def _mock_context_with_secrets(*args, **kwargs):
    ctx = _RealMockContext(*args, **kwargs)
    ctx.secrets = MockSecretStore({"notes_api_key": "test-notes-key"})
    return ctx


_testing_mod.MockContext = _mock_context_with_secrets
