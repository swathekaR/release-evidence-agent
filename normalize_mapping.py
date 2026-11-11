
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

mapping_file = BASE_DIR / "source_issue_mapping.json"
dataset_file = BASE_DIR / "inputs" / "dataset.json"

with open(mapping_file, "r", encoding="utf-8") as file:
    mapping = json.load(file)

with open(dataset_file, "r", encoding="utf-8") as file:
    dataset = json.load(file)

# Convert mapping source IDs to uppercase.
normalized_mapping = {
    source_id.upper(): issue_key
    for source_id, issue_key in mapping.items()
}

dataset_ids = {
    record["source_id"].upper()
    for record in dataset["records"]
}

mapping_ids = set(normalized_mapping.keys())

missing = dataset_ids - mapping_ids
extra = mapping_ids - dataset_ids

if missing or extra:
    raise ValueError(
        f"Mapping validation failed. "
        f"Missing: {list(missing)[:10]}, "
        f"Extra: {list(extra)[:10]}"
    )

if len(normalized_mapping) != len(mapping):
    raise ValueError("Duplicate IDs detected after normalization.")

# Save a backup before updating.
backup_file = BASE_DIR / "source_issue_mapping_backup.json"

with open(backup_file, "w", encoding="utf-8") as file:
    json.dump(mapping, file, indent=4)

with open(mapping_file, "w", encoding="utf-8") as file:
    json.dump(normalized_mapping, file, indent=4)

print("========== MAPPING NORMALIZATION ==========")
print("Original mappings:", len(mapping))
print("Normalized mappings:", len(normalized_mapping))
print("Missing IDs:", len(missing))
print("Extra IDs:", len(extra))
print("Backup:", backup_file)
print("Mapping successfully normalized.")
