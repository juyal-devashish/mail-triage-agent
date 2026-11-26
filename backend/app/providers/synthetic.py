"""The SYNTHETIC inbox as a provider. Label changes live only in the local store."""

from app.domain.types import Message
from app.synth.inbox import generate


class SyntheticProvider:
    name = "synthetic"
    authoritative = False

    def __init__(self, seed: int = 7, size: int = 150) -> None:
        self._messages, _ = generate(seed=seed, size=size)  # the answer key is dropped here on purpose
        self.calls: list[tuple[list[str], list[str], list[str]]] = []

    def fetch(self) -> list[Message]:
        return list(self._messages)

    def modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        self.calls.append((list(ids), list(add), list(remove)))
