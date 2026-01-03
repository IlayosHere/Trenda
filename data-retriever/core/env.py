from dotenv import load_dotenv
from pathlib import Path

# Absolute path to project root
BASE_DIR = Path(__file__).resolve().parents[1]

# Load .env from project root (one level up from data-retriever)
load_dotenv(BASE_DIR.parent / ".env")
