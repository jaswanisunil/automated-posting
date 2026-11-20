from abc import ABC, abstractmethod

from app.schemas import PostingResult


class Platform(ABC):
    name: str

    @abstractmethod
    async def post(self, message: str) -> PostingResult:
        """Publish a message and return the platform's result."""
