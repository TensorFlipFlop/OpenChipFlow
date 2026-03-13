#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

def repair_json_content(content: str) -> str:
    """Robustly extract and repair JSON from text."""
    # 1. Remove Markdown code blocks if present
    # Matches ```json <content> ``` or just ``` <content> ```
    content = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", content, flags=re.DOTALL)
    
    # 2. Find the first '[' or '{' and the last ']' or '}'
    # This strips leading/trailing conversational filler
    list_start = content.find('[')
    obj_start = content.find('{')
    
    start = -1
    end = -1
    
    if list_start != -1 and (obj_start == -1 or list_start < obj_start):
        start = list_start
        end = content.rfind(']')
    elif obj_start != -1:
        start = obj_start
        end = content.rfind('}')
        
    if start != -1 and end != -1 and end > start:
        content = content[start : end + 1]
    
    # 3. Basic syntax cleanup: remove trailing commas in arrays/objects
    # This is a common LLM error
    content = re.sub(r",\s*([\]}])", r"\1", content)
    
    return content

def main():
    if len(sys.argv) < 2:
        print("Usage: json_cleaner.py <file_path>")
        sys.exit(1)
        
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File {file_path} not found")
        sys.exit(1)
        
    try:
        raw_content = file_path.read_text(encoding="utf-8")
        if not raw_content.strip():
            return

        cleaned_content = repair_json_content(raw_content)
        
        # Validate by parsing
        data = json.loads(cleaned_content)
        
        # Write back pretty-printed and clean
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[OK] Successfully cleaned and validated {file_path}")
        
    except Exception as e:
        print(f"[ERROR] Failed to repair JSON in {file_path}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
