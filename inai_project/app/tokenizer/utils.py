import re
import json
import os

# ✅ Path from project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# File paths
NEW_MAINVOCAB_PATH = os.path.join(DATA_DIR, "new_mainvocab.json")
UNIQUE_IDS_PATH = os.path.join(DATA_DIR, "unique_ids.json")
INDIVIDUAL_WORDS_PATH = os.path.join(DATA_DIR, "individual_words.json")

# Load vocab
if os.path.exists(NEW_MAINVOCAB_PATH):
    with open(NEW_MAINVOCAB_PATH, "r", encoding="utf-8") as f:
        vocab = json.load(f)
else:   
    vocab = {}

# Load final tokens (sentence-level unique ids)
if os.path.exists(UNIQUE_IDS_PATH):
    with open(UNIQUE_IDS_PATH, "r", encoding="utf-8") as f:
        final_tokens = json.load(f)
else:
    final_tokens = {}

# Load individual words
if os.path.exists(INDIVIDUAL_WORDS_PATH):
    with open(INDIVIDUAL_WORDS_PATH, "r", encoding="utf-8") as f:
        individual_words = json.load(f)
else:
    individual_words = {}

# Start token id
max_token_id = max([*individual_words.values(), *vocab.values(), *final_tokens.values()], default=1000)


def save_data():
    """Save all JSON files"""
    with open(NEW_MAINVOCAB_PATH, "w", encoding="utf-8") as f:
        json.dump(vocab, f, indent=2, ensure_ascii=False)
    with open(UNIQUE_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(final_tokens, f, indent=2, ensure_ascii=False)
    with open(INDIVIDUAL_WORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(individual_words, f, indent=2, ensure_ascii=False)


def get_or_create_token(word: str) -> int:
    """Fetch token ID for a word or create new if missing (case-sensitive)."""
    global max_token_id

    # ✅ Case-sensitive check (Roshni ≠ roshni ≠ ROSHNI)
    if word in individual_words:
        return individual_words[word]
    if word in vocab:
        return vocab[word]

    # 🔹 Create new token for unseen word (case-sensitive)
    max_token_id += 1
    individual_words[word] = max_token_id
    vocab[word] = max_token_id
    save_data()
    return max_token_id


def tokenize_text(text: str):
    """
    Tokenize input text into word tokens.
    Case-sensitive IDs (Roshni ≠ roshni ≠ ROSHNI).
    Auto-create token ids for new words.
    Assign a unique sentence id if it's new.
    """
    global max_token_id

    original_text = text.strip()
    # ✅ preserve input exactly (case-sensitive words)
    original_words = re.findall(r"[A-Za-z]+", original_text)

    # ✅ Case-sensitive tokens
    token_sequence = [get_or_create_token(word) for word in original_words]
    token_count = len(token_sequence)
    total_chars = len(original_text)

    # Save unique sentence token (case-sensitive key)
    if original_words:
        key = " ".join(original_words)
        if key not in final_tokens:
            max_token_id += 1
            final_tokens[key] = max_token_id
            save_data()

    return {
        "tokens": token_count,
        "words": f"Found {token_count} words: {original_words}",
        "id": f"Token sequence: {token_sequence}",
        "capital_abcd": f"Total characters (including spaces & punctuation): {total_chars}",
        "sentence_token": final_tokens.get(" ".join(original_words))
    }
