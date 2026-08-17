"""
Diagnostic tool — run this directly to see exactly why GEMINI_API_KEY
isn't loading, instead of guessing.

Usage:
    python check_env.py
"""
from pathlib import Path

root = Path(__file__).resolve().parent
env_path = root / ".env"

print(f"Looking for .env at: {env_path}")
print(f"Exists: {env_path.exists()}")

if env_path.exists():
    print(f"File size: {env_path.stat().st_size} bytes")
    raw = env_path.read_bytes()
    print(f"First 4 bytes (hex): {raw[:4].hex()}  "
          f"(should NOT start with fffe/feff — that means UTF-16, which breaks parsing)")

    try:
        text = raw.decode("utf-8-sig")  # handles BOM if present
    except UnicodeDecodeError:
        print("Could not decode as UTF-8 — file is likely saved in the wrong encoding "
              "(e.g. UTF-16 from Notepad). Recreate it with the PowerShell command below.")
        text = None

    if text is not None:
        print("\n--- Raw content between markers ---")
        print(f">>>{text}<<<")
        print("--- end content ---\n")

        if "GEMINI_API_KEY" not in text:
            print("PROBLEM: the file does not contain the text 'GEMINI_API_KEY'.")
        elif "=" not in text:
            print("PROBLEM: no '=' sign found.")
        else:
            for line in text.splitlines():
                if line.strip().startswith("GEMINI_API_KEY"):
                    key_part = line.split("=", 1)[1].strip() if "=" in line else ""
                    print(f"Found line, key value length: {len(key_part)} characters")
                    if key_part.startswith('"') or key_part.startswith("'"):
                        print("PROBLEM: value is wrapped in quotes — remove them.")
                    if not key_part:
                        print("PROBLEM: value after '=' is empty.")
else:
    print("\nPROBLEM: no .env file at this exact path.")
    print("\nCreate it with this PowerShell command (run from this same folder):")
    print('  Set-Content -Path ".env" -Value "GEMINI_API_KEY=your-gemini-key-here" -Encoding ascii')

# Also try loading it the same way client.py does, to confirm end to end.
try:
    from dotenv import load_dotenv
    import os
    load_dotenv(dotenv_path=env_path)
    loaded = os.environ.get("GEMINI_API_KEY")
    print(f"\nload_dotenv() result -> GEMINI_API_KEY is: "
          f"{'SET (' + str(len(loaded)) + ' chars)' if loaded else 'NOT SET'}")
except ImportError:
    print("\n(python-dotenv not installed in this environment — pip install python-dotenv)")
