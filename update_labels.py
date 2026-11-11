
import os
import json
import argparse
import requests

from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAPPING_FILE = BASE_DIR / "source_issue_mapping.json"

load_dotenv(BASE_DIR / ".env")

DATASET_LABEL = "tyn-release-assessment-v2"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Add the dataset label to existing Jira issues."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually update Jira. Without this flag, only preview changes."
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    dry_run = not args.execute

    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_API_TOKEN")

    if not all([jira_url, jira_email, jira_token]):
        raise ValueError("Missing Jira configuration in .env")

    jira_url = jira_url.rstrip("/")

    if not MAPPING_FILE.exists():
        raise FileNotFoundError(f"Mapping file not found: {MAPPING_FILE}")

    with open(MAPPING_FILE, "r", encoding="utf-8") as file:
        mapping = json.load(file)

    if len(mapping) != 400:
        raise ValueError(
            f"Expected 400 mappings, found {len(mapping)}. Aborting."
        )

    session = requests.Session()
    session.auth = HTTPBasicAuth(jira_email, jira_token)
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json"
    })

    updated = 0
    already_present = 0
    failed = []

    print("Mode:", "DRY RUN" if dry_run else "EXECUTION")
    print("Total mapped issues:", len(mapping))

    for source_id, issue_key in mapping.items():
        try:
            response = session.get(
                f"{jira_url}/rest/api/3/issue/{issue_key}",
                params={"fields": "labels"},
                timeout=30
            )
            response.raise_for_status()

            current_labels = response.json()["fields"].get("labels", [])

            if DATASET_LABEL in current_labels:
                already_present += 1
                continue

            new_labels = current_labels + [DATASET_LABEL]

            if dry_run:
                print(f"[DRY RUN] {issue_key}: would add label")
                updated += 1
                continue

            update_response = session.put(
                f"{jira_url}/rest/api/3/issue/{issue_key}",
                json={"fields": {"labels": new_labels}},
                timeout=30
            )
            update_response.raise_for_status()

            updated += 1
            print(f"[UPDATED] {issue_key}")

        except requests.RequestException as error:
            status = (
                error.response.status_code
                if error.response is not None
                else "No response"
            )

            failed.append({
                "source_id": source_id,
                "issue_key": issue_key,
                "status": status,
                "error": str(error)
            })

            print(f"[FAILED] {issue_key}: {error}")

    print("\n========== LABEL UPDATE REPORT ==========")
    print("Total mapped issues:", len(mapping))
    print("Updated / planned:", updated)
    print("Already labelled:", already_present)
    print("Failed:", len(failed))
    print("Dry run:", dry_run)

    if failed:
        error_file = BASE_DIR / "label_update_errors.json"
        with open(error_file, "w", encoding="utf-8") as file:
            json.dump(failed, file, indent=4)

        print("Errors saved to:", error_file)


if __name__ == "__main__":
    main()
