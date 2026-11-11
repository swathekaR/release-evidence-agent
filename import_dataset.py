
import os
import json
import argparse
import requests

from pathlib import Path
from collections import Counter
from dotenv import load_dotenv


# --------------------------------------------------
# 1. LOAD CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

JIRA_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

DATASET_PATH = BASE_DIR / "inputs" / "dataset.json"

if not all([JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, PROJECT_KEY]):
    raise ValueError("Missing Jira configuration. Check your .env file.")


session = requests.Session()
session.auth = (JIRA_EMAIL, JIRA_TOKEN)
session.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json"
})


# --------------------------------------------------
# 2. JIRA API HELPER
# --------------------------------------------------

def jira_request(method, endpoint, **kwargs):
    url = f"{JIRA_URL}{endpoint}"

    response = session.request(
        method,
        url,
        timeout=60,
        **kwargs
    )

    if response.status_code == 429:
        raise RuntimeError("Jira rate limit reached. Please retry later.")

    if not response.ok:
        raise RuntimeError(
            f"Jira API error: {response.status_code}\n"
            f"{response.text[:1000]}"
        )

    if response.status_code == 204 or not response.text:
        return None

    return response.json()


# --------------------------------------------------
# 3. LOAD AND VALIDATE DATASET
# --------------------------------------------------

def load_dataset():

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    with open(DATASET_PATH, "r", encoding="utf-8") as file:
        dataset = json.load(file)

    records = dataset.get("records", [])

    if not records:
        raise ValueError("Dataset contains no records.")

    source_ids = [
        record.get("source_id")
        for record in records
    ]

    if None in source_ids:
        raise ValueError("Some records are missing source_id.")

    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Duplicate source_id values found.")

    required_fields = [
        "source_id",
        "kind",
        "summary",
        "description",
        "comments",
        "links"
    ]

    for index, record in enumerate(records):
        missing = [
            field for field in required_fields
            if field not in record
        ]

        if missing:
            raise ValueError(
                f"Record {index} is missing fields: {missing}"
            )

    return dataset


# --------------------------------------------------
# 4. CONVERT TEXT TO JIRA DOCUMENT FORMAT
# --------------------------------------------------

def create_adf(text):

    paragraphs = []

    for line in str(text or "").splitlines():
        paragraphs.append({
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": line or " "
                }
            ]
        })

    if not paragraphs:
        paragraphs.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": " "}
            ]
        })

    return {
        "type": "doc",
        "version": 1,
        "content": paragraphs
    }


# --------------------------------------------------
# 5. FETCH EXISTING IMPORTED ISSUES
# --------------------------------------------------

def get_existing_source_ids():

    existing_ids = set()
    next_page_token = None

    while True:

        params = {
            "jql": f'project = "{PROJECT_KEY}"',
            "fields": "labels",
            "maxResults": 100
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        result = jira_request(
            "GET",
            "/rest/api/3/search/jql",
            params=params
        )

        for issue in result.get("issues", []):

            labels = issue.get("fields", {}).get("labels", [])

            for label in labels:
                if label.startswith("source-"):
                    existing_ids.add(label.replace("source-", "", 1).upper())

        next_page_token = result.get("nextPageToken")

        if not next_page_token:
            break

    return existing_ids


# --------------------------------------------------
# 6. PREPARE JIRA ISSUE
# --------------------------------------------------

def prepare_issue(record):

    source_id = record["source_id"]
    kind = record["kind"].lower()

    summary = str(record.get("summary") or source_id)

    # Jira summaries have a length limit.
    jira_summary = f"[{source_id}] {summary}"[:255]

    details = [
        f"Source ID: {source_id}",
        f"Record Type: {kind}",
        f"Release: {record.get('release', 'Not specified')}",
        f"Recorded Status: {record.get('recorded_status', 'Not specified')}",
        "",
        "Original Description:",
        str(record.get("description") or ""),
        "",
        "Original Comments Count: "
        f"{len(record.get('comments', []))}",
        "Original Links: "
        f"{json.dumps(record.get('links', []), ensure_ascii=False)}"
    ]

    labels = [
        f"source-{source_id.lower()}",
        f"kind-{kind}",
        "dataset-tyn-release-assessment-v2"
    ]

    return {
        "fields": {
            "project": {
                "key": PROJECT_KEY
            },
            "issuetype": {
                "name": "Task"
            },
            "summary": jira_summary,
            "description": create_adf("\n".join(details)),
            "labels": labels
        }
    }


# --------------------------------------------------
# 7. CREATE JIRA ISSUE
# --------------------------------------------------

def create_jira_issue(record):

    payload = prepare_issue(record)

    result = jira_request(
        "POST",
        "/rest/api/3/issue",
        json=payload
    )

    return result.get("key")


# --------------------------------------------------
# 8. MAIN IMPORT PROCESS
# --------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Import assessment records into Jira."
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually create Jira issues. Without this, only dry-run."
    )

    args = parser.parse_args()

    dataset = load_dataset()
    records = dataset["records"]

    print("\n========== DATASET SUMMARY ==========")
    print("Dataset:", dataset.get("dataset_label"))
    print("Total records:", len(records))
    print("Target:", dataset.get("target"))

    counts = Counter(
        record.get("kind", "unknown")
        for record in records
    )

    for kind, count in counts.items():
        print(f"{kind}: {count}")

    print("\n========== JIRA IMPORT ==========")

    existing_ids = get_existing_source_ids()

    new_records = [
        record for record in records
        if record["source_id"].upper() not in existing_ids
    ]

    skipped_count = len(records) - len(new_records)

    print("Already imported:", skipped_count)
    print("New records:", len(new_records))

    if not args.execute:

        print("\nDRY RUN COMPLETED")
        print("No Jira issues were created.")
        print("Run with --execute to perform the import.")

        return

    created_count = 0
    failed_count = 0

    for index, record in enumerate(new_records, start=1):

        source_id = record["source_id"]

        try:
            issue_key = create_jira_issue(record)

            print(
                f"[{index}/{len(new_records)}] "
                f"{source_id} -> {issue_key}"
            )

            created_count += 1

        except Exception as error:

            print(f"FAILED: {source_id}")
            print("Reason:", error)

            failed_count += 1

    print("\n========== IMPORT RESULT ==========")
    print("Created:", created_count)
    print("Skipped:", skipped_count)
    print("Failed:", failed_count)


if __name__ == "__main__":
    main()
