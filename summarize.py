import os, openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("GPT_MODEL", "gpt-3.5-turbo-0125")


def summarize_text(snapshot: str) -> str:
    prompt = (
        "You are a crypto market analyst. In 120 words or fewer, write a concise, "
        "engaging market recap for retail traders. Highlight notable moves, "
        "overall sentiment, and any coin with >5% price change.\n\n"
        f"Market data:\n{snapshot}"
    )
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=180,
    )
    return resp.choices[0].message.content.strip()