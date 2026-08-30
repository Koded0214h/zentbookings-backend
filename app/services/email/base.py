from __future__ import annotations

import abc


class EmailSender(abc.ABC):
    @abc.abstractmethod
    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        ...
