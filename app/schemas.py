import re
from datetime import date as Date, time as Time
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


_URL_SCHEME_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_URL_PATTERN = re.compile(r"""[a-z][a-z0-9+.-]*://[^\s<>"']+""", re.IGNORECASE)
_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_TRAILING_URL_PUNCTUATION = ".,!?;:)]}"


class PostingRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("message")
    @classmethod
    def validate_single_cta_url(cls, message: str) -> str:
        if len(_URL_SCHEME_PATTERN.findall(message)) != 1:
            raise ValueError("Message must include exactly one HTTP or HTTPS URL.")

        match = _URL_PATTERN.search(message)
        if match is None:
            raise ValueError("Message must include exactly one HTTP or HTTPS URL.")

        url = match.group().rstrip(_TRAILING_URL_PUNCTUATION)
        try:
            parsed_url = _URL_ADAPTER.validate_python(url)
        except ValidationError as error:
            raise ValueError("Message must include a valid HTTP or HTTPS URL.") from error

        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError("URL must not contain embedded credentials.")

        return message


class PostingError(str, Enum):
    TIMEOUT = "The platform request timed out."
    FAILURE = "The platform could not complete the post."
    NOT_CONFIGURED = "The platform is not configured."
    AUTHENTICATION = "The platform authentication failed."
    RATE_LIMITED = "The platform rate limit was reached."
    REJECTED = "The platform rejected the submitted content."
    DESTINATION_UNAVAILABLE = "The platform could not access the configured destination."
    CONTENT_TOO_LONG = "The submitted message exceeds the platform's post-length limit."
    INVALID_RESPONSE = "The platform returned an invalid response."


class PostingResult(BaseModel):
    platform: str
    status: Literal["success", "failed"]
    posted_url: AnyHttpUrl | None = None
    public_access: bool | None = None
    date: Date | None = None
    time: Time | None = None
    error: PostingError | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "PostingResult":
        if self.status == "success":
            if self.date is None or self.time is None:
                raise ValueError(
                    "Successful results require date and time information."
                )
            if self.error is not None:
                raise ValueError("Successful results cannot contain an error.")
        elif self.error is None:
            raise ValueError("Failed results require a standardised error.")

        return self


class PostingResponse(BaseModel):
    success: bool
    results: list[PostingResult]
