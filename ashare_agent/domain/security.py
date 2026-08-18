from pydantic import BaseModel


class Security(BaseModel):
    code: str
    name: str
