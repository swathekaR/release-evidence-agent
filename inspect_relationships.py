
import json
from pathlib import Path
from collections import Counter

path = Path("inputs") / "dataset.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["records"]

print("DATASET LABEL:", data.get("dataset_label"))

print("\n========== COMMENT STRUCTURE ==========")

comment_shapes = Counter()
comment_samples = []

for record in records:
    for comment in record.get("comments", []):
        comment_shapes[type(comment).__name__] += 1

        if len(comment_samples) < 3:
            comment_samples.append({
                "record_id": record["source_id"],
                "comment": comment
            })

print("Comment types:", comment_shapes)

for sample in comment_samples:
    print(json.dumps(sample, indent=2, ensure_ascii=False))


print("\n========== LINK STRUCTURE ==========")

link_shapes = Counter()
link_samples = []

for record in records:
    for link in record.get("links", []):
        link_shapes[type(link).__name__] += 1

        if len(link_samples) < 5:
            link_samples.append({
                "record_id": record["source_id"],
                "link": link
            })

print("Link types:", link_shapes)

for sample in link_samples:
    print(json.dumps(sample, indent=2, ensure_ascii=False))


print("\n========== RECORD EXAMPLES ==========")

for kind in ["requirement", "manifest"]:
    record = next(
        (r for r in records if r.get("kind") == kind),
        None
    )

    if record:
        print(f"\n{kind.upper()}:")
        print(json.dumps(record, indent=2, ensure_ascii=False)[:5000])
