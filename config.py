import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key "
        "(see the Setup section in README.md)."
    )

client = OpenAI(api_key=API_KEY)

CHAT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "text-embedding-3-small"
