from pydantic import BaseModel


class SessionOpenerOutput(BaseModel):
    message: str
