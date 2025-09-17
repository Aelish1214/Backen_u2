from pydantic import BaseModel
from typing import List

class TextInput(BaseModel):
    text: str

class TokenResponse(BaseModel):
    tokens: int
    words: str
    id: str
    capital_abcd: str
