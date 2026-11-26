import pytest

from app.providers.synthetic import SyntheticProvider
from app.store import Store


class Clock:
    def __init__(self) -> None:
        self.t = 0

    def __call__(self) -> str:
        self.t += 1
        return f"2026-11-23T08:00:{self.t % 60:02d}+00:00"


@pytest.fixture
def provider() -> SyntheticProvider:
    return SyntheticProvider()


@pytest.fixture
def store(provider: SyntheticProvider) -> Store:
    s = Store(":memory:", now=Clock())
    s.upsert_messages(provider.fetch())
    return s
