from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Selector:
    client: str
    provider: str | None = None
    model: str | None = None

    def matches(self, client: str, provider: str | None = None, model: str | None = None) -> bool:
        if self.client != client:
            return False
        if self.provider is not None:
            if provider is None or self.provider != provider:
                return False
        if self.model is not None:
            if model is None or self.model != model:
                return False
        return True


def parse_selector(value: str) -> Selector:
    if value is None or value == "":
        raise ValueError("selector must not be empty")
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid selector '{value}': expected client, client:provider, or client:provider:model")
    if any(part == "" for part in parts):
        raise ValueError(f"invalid selector '{value}': selector IDs must not be empty")
    return Selector(client=parts[0], provider=parts[1] if len(parts) >= 2 else None, model=parts[2] if len(parts) == 3 else None)


def parse_selectors(values: list[str] | None) -> list[Selector]:
    return [parse_selector(v) for v in (values or [])]


def selection_matches(selectors: list[Selector], client: str, provider: str | None = None, model: str | None = None) -> bool:
    if not selectors:
        return True
    return any(selector.matches(client, provider, model) for selector in selectors)
