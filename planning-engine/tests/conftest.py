"""Shared fixtures.

`generate_history` takes a few seconds, so it is generated once per test
session rather than per test. It is deterministic (seeded from the config),
which is what makes session scoping safe here.
"""

import pytest

from dcww_planning.config import default_config
from dcww_planning.synth import generate_history


@pytest.fixture(scope="session")
def config():
    return default_config()


@pytest.fixture(scope="session")
def history():
    return generate_history()


@pytest.fixture(scope="session")
def daily(history):
    return history.daily


@pytest.fixture(scope="session")
def profiles(history):
    return history.profiles
