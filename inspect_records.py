
import json
from pathlib import Path
from collections import Counter

# Locate the dataset
DATASET_PATH = Path("inputs") / "dataset.json"

if not DATASET_PATH.exists():
    raise FileNotFoundError(
        f"Dataset not found: {DATASET_PATH.resolve()}"
    )

# Read JSON
with open(DATASET_PATH, "r", encoding="utf-8") as file:
    dataset = json.load(file)

records = dataset.get("records", [])

print("\n========== DATASET OVERVIEW ==========")
print("Dataset:", dataset.get("dataset_label"))
print("Total records:", len(records))
print("Target:", dataset.get("target"))

# Count record types
kind_counts = Counter(
    record.get("kind", "unknown")
    for record in records
)

print("\n========== RECORD TYPES ==========")
for kind, count in kind_counts.items():
    print(f"{kind}: {count}")

# Count comments and links
total_comments = sum(
    len(record.get("comments", []))
    for record in records
)

total_links = sum(
    len(record.get("links", []))
    for record in records
)

print("\n========== RELATIONSHIPS ==========")
print("Total comments:", total_comments)
print("Total links:", total_links)

# Check unique source IDs
source_ids = [
    record.get("source_id")
    for record in records
]

print("Unique source IDs:", len(set(source_ids)))
print("Missing source IDs:", source_ids.count(None))

# Show record fields
if records:
    print("\n========== RECORD FIELDS ==========")
    print(list(records[0].keys()))

print("\nDataset inspection completed.")
