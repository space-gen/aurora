import json
import os
from pathlib import Path

DATA_DIR = Path("data_processing")
README_PATH = DATA_DIR / "README.md"

def main():
    samples = {}
    for task_file in DATA_DIR.glob("*.json"):
        if task_file.name == "model_accuracy.json":
            continue
        
        try:
            with open(task_file, "r") as f:
                data = json.load(f)
                if data and isinstance(data, list):
                    samples[task_file.stem] = {
                        "url": data[0]["url"],
                        "id": data[0]["id"],
                        "serial_number": data[0]["serial_number"]
                    }
        except Exception as e:
            print(f"Error reading {task_file}: {e}")

    if not samples:
        print("No samples found.")
        return

    content = "# SolarHub Data Processing Directory\n\nThis directory contains grouped task JSON files ready for annotation.\n\n## Sample Data URLs (Best-in-Class NASA SDO JPGs)\n\n"
    for task, data in sorted(samples.items()):
        url = data["url"]
        record_id = data["id"]
        serial = data["serial_number"]
        content += f"### {task.replace('_', ' ').title()} (ID: {record_id})\n"
        content += f"![{task}]({url})\n"
        content += f"- URL: {url}\n"
        content += f"- Serial Number: {serial}\n\n"

    with open(README_PATH, "w") as f:
        f.write(content)
    print("README updated with samples.")

if __name__ == "__main__":
    main()
