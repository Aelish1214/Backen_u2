from fastapi import APIRouter
from .schemas import TextInput, TokenResponse
from .utils import tokenize_text

router = APIRouter(prefix="/tokenizer", tags=["Tokenizer"])

@router.post("/analyze", response_model=TokenResponse)
def analyze_text(data: TextInput):
    return tokenize_text(data.text)
