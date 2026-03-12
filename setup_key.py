"""Saves your Anthropic API key to .env — run once."""
key = input("Paste your Anthropic API key here: ").strip()
if key:
    with open(".env", "w") as f:
        f.write(f"ANTHROPIC_API_KEY={key}\n")
    print(f"[OK] Key saved to .env ({key[:10]}...)")
else:
    print("[ERROR] No key entered.")
    exit(1)
