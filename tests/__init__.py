"""Test suite.

This file makes ``tests`` a real package. Two reasons, both practical:
shared test doubles can then live in ``tests.fakes`` and be imported by
name, and mypy stops seeing the same file under two module names (once
as ``test_devices``, once as ``tests.test_devices``) — which it treats
as a hard error.
"""
