
import os
import json
import time
import argparse
from pathlib import Path
from collections import Counter

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATASET_FILE = BASE_DIR / "inputs" / "dataset.json"
MAPPING_FILE = BASE_DIR / "source_issue_mapping.json"
AUDIT_FILE = BASE_DIR / "jira_import_audit.json"

DATASET_LABEL = "tyn-release-assessment-v2"
LINK_TYPE = "Relates"

load_dotenv(BASE_DIR / ".env")

JIRA_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

parser = argparse.ArgumentParser(
    description="Import dataset comments and relationships into existing Jira issues."
)
parser.add_argument(
    "--execute",
    action="store_true",
    help="Actually import comments and links. Default is dry run."
)
ARGS = parser.parse_args()
DRY_RUN = not ARGS.execute


# --------------------------------------------------
# VALIDATE CONFIGURATION AND INPUT FILES
# --------------------------------------------------

if not all([JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, PROJECT_KEY]):
    raise ValueError("Missing Jira configuration in .env")

JIRA_URL = JIRA_URL.rstrip("/")

if not DATASET_FILE.exists():
    raise FileNotFoundError(DATASET_FILE)

if not MAPPING_FILE.exists():
    raise FileNotFoundError(MAPPING_FILE)

with open(DATASET_FILE, "r", encoding="utf-8") as file:
    dataset = json.load(file)

with open(MAPPING_FILE, "r", encoding="utf-8") as file:
    mapping = json.load(file)

records = dataset.get("records", [])

if len(mapping) != 400:
    raise ValueError(
        f"Expected 400 mapped issues, found {len(mapping)}."
    )

if dataset.get("dataset_label") != DATASET_LABEL:
    raise ValueError("Dataset label does not match expected value.")

record_by_id = {
    record["source_id"]: record
    for record in records
}

if len(record_by_id) != len(records):
    raise ValueError("Duplicate source IDs found in dataset.")

missing_mapping = [
    source_id for source_id in record_by_id
    if source_id not in mapping
]

if missing_mapping:
    raise ValueError(
        f"Missing Jira mappings for: {missing_mapping[:10]}"
    )

if len(records) != 400:
    raise ValueError(
        f"Expected 400 dataset records, found {len(records)}."
    )


# --------------------------------------------------
# JIRA SESSION AND REQUEST HELPERS
# --------------------------------------------------

session = requests.Session()
session.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)
session.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json"
})


def jira_request(method, endpoint, **kwargs):
    """Retry temporary failures for safe Jira API operations."""

    url = f"{JIRA_URL}{endpoint}"
    last_error = None

    for attempt in range(4):
        try:
            response = session.request(
                method,
                url,
                timeout=45,
                **kwargs
            )

            if response.status_code == 429 or response.status_code >= 500:
                wait = min(2 ** attempt, 20)
                print(
                    f"[RETRY] HTTP {response.status_code}; "
                    f"waiting {wait}s"
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        except RequestException as error:
            last_error = error
            wait = min(2 ** attempt, 20)
            print(f"[RETRY] {error}; waiting {wait}s")
            time.sleep(wait)

    raise RuntimeError(
        f"Jira request failed after retries: {last_error}"
    )


def adf_to_text(node):
    """Extract readable text from Jira's Atlassian Document Format."""

    if isinstance(node, dict):
        parts = []

        if node.get("type") == "text":
            parts.append(node.get("text", ""))

        for child in node.get("content", []):
            parts.append(adf_to_text(child))

        if node.get("type") in ["paragraph", "heading"]:
            parts.append("\n")

        return "".join(parts)

    if isinstance(node, list):
        return "".join(adf_to_text(item) for item in node)

    return ""


def comment_to_adf(comment_text):
    """Keep the original fictional event text unchanged."""

    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": comment_text
                    }
                ]
            }
        ]
    }


def get_all_comments(issue_key):
    """Read all existing Jira comments, including paginated results."""

    comments = []
    start_at = 0
    page_size = 100

    while True:
        response = jira_request(
            "GET",
            f"/rest/api/3/issue/{issue_key}/comment",
            params={
                "startAt": start_at,
                "maxResults": page_size
            }
        )

        result = response.json()
        page = result.get("comments", [])
        comments.extend(page)

        if not page or start_at + len(page) >= result.get(
            "total", len(comments)
        ):
            break

        start_at += len(page)

    return comments


def save_audit(audit):
    """Persist progress so results remain available after interruption."""

    with open(AUDIT_FILE, "w", encoding="utf-8") as file:
        json.dump(audit, file, indent=4, ensure_ascii=False)


# --------------------------------------------------
# BUILD AND VALIDATE RELATIONSHIPS
# --------------------------------------------------

relationships = set()

for record in records:
    source_id = record["source_id"]

    for linked_source_id in record.get("links", []):
        if linked_source_id not in mapping:
            raise ValueError(
                f"Unmapped link target: {source_id} -> "
                f"{linked_source_id}"
            )

        if source_id == linked_source_id:
            raise ValueError(
                f"Self-link found for {source_id}"
            )

        # Normalize the pair so reciprocal source links
        # are only imported once.
        pair = tuple(sorted([source_id, linked_source_id]))
        relationships.add(pair)

if len(relationships) != 76:
    raise ValueError(
        f"Expected 76 unique relationships, "
        f"found {len(relationships)}. Review before importing."
    )


# --------------------------------------------------
# AUDIT STRUCTURE
# --------------------------------------------------

audit = {
    "dataset_label": DATASET_LABEL,
    "project": PROJECT_KEY,
    "dry_run": DRY_RUN,
    "issues_checked": 0,
    "comments": {
        "expected": sum(
            len(record.get("comments", []))
            for record in records
        ),
        "created": 0,
        "already_present": 0,
        "failed": []
    },
    "links": {
        "expected": len(relationships),
        "created": 0,
        "already_present": 0,
        "failed": []
    },
    "label_failures": [],
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
}


# --------------------------------------------------
# STEP A: VERIFY ALL 400 LABELS BEFORE IMPORTING
# --------------------------------------------------

print("\n========== VERIFYING DATASET LABELS ==========")

for source_id, issue_key in mapping.items():
    try:
        response = jira_request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": "labels"}
        )

        labels = response.json()["fields"].get("labels", [])

        if DATASET_LABEL not in labels:
            audit["label_failures"].append({
                "source_id": source_id,
                "issue_key": issue_key,
                "error": "Required dataset label missing"
            })

        audit["issues_checked"] += 1

    except Exception as error:
        audit["label_failures"].append({
            "source_id": source_id,
            "issue_key": issue_key,
            "error": str(error)
        })

if audit["label_failures"]:
    save_audit(audit)
    raise RuntimeError(
        f"{len(audit['label_failures'])} issues failed label "
        "verification. Fix these before importing comments."
    )

print("Verified:", audit["issues_checked"], "issues")
print("All issues have the required dataset label.")


# --------------------------------------------------
# STEP B: IMPORT COMMENTS
# --------------------------------------------------

print("\n========== IMPORTING COMMENTS ==========")
print("Mode:", "DRY RUN" if DRY_RUN else "EXECUTION")

for source_id, issue_key in mapping.items():
    record = record_by_id[source_id]
    source_comments = record.get("comments", [])

    if not source_comments:
        continue

    try:
        existing_comments = get_all_comments(issue_key)

        # Count exact text occurrences, not just unique strings.
        existing_texts = Counter(
            adf_to_text(comment.get("body", {})).rstrip("\n")
            for comment in existing_comments
        )

        required_texts = Counter(source_comments)

        for comment_text, required_count in required_texts.items():
            existing_count = existing_texts[comment_text]

            missing_count = max(
                0,
                required_count - existing_count
            )

            for _ in range(missing_count):
                if DRY_RUN:
                    print(
                        f"[DRY RUN] {issue_key}: "
                        "would add original comment"
                    )
                    audit["comments"]["created"] += 1
                    continue

                try:
                    jira_request(
                        "POST",
                        f"/rest/api/3/issue/{issue_key}/comment",
                        json={
                            "body": comment_to_adf(comment_text)
                        }
                    )

                    audit["comments"]["created"] += 1
                    existing_texts[comment_text] += 1

                except Exception as post_error:
                    # A connection can fail after Jira has accepted
                    # a POST. Re-read before recording a failure.
                    try:
                        refreshed = get_all_comments(issue_key)
                        refreshed_texts = Counter(
                            adf_to_text(
                                item.get("body", {})
                            ).rstrip("\n")
                            for item in refreshed
                        )

                        if refreshed_texts[comment_text] > existing_texts[
                            comment_text
                        ]:
                            existing_texts[comment_text] += 1
                            audit["comments"]["created"] += 1
                            continue

                    except Exception:
                        pass

                    audit["comments"]["failed"].append({
                        "source_id": source_id,
                        "issue_key": issue_key,
                        "error": str(post_error)
                    })

            audit["comments"]["already_present"] += (
                required_count - missing_count
            )

        print(f"[COMMENTS CHECKED] {issue_key}")

    except Exception as error:
        audit["comments"]["failed"].append({
            "source_id": source_id,
            "issue_key": issue_key,
            "error": str(error)
        })

    save_audit(audit)


# --------------------------------------------------
# STEP C: IMPORT ACTUAL JIRA ISSUE LINKS
# --------------------------------------------------

print("\n========== IMPORTING ISSUE LINKS ==========")

for source_a, source_b in sorted(relationships):
    issue_a = mapping[source_a]
    issue_b = mapping[source_b]

    try:
        # Jira's issuelinks field shows links in either direction.
        response = jira_request(
            "GET",
            f"/rest/api/3/issue/{issue_a}",
            params={"fields": "issuelinks"}
        )

        existing_links = response.json()["fields"].get(
            "issuelinks", []
        )

        already_linked = False

        for link in existing_links:
            link_type = link.get("type", {}).get("name")

            linked_issue = (
                link.get("outwardIssue")
                or link.get("inwardIssue")
                or {}
            )

            if (
                linked_issue.get("key") == issue_b
                and link_type == LINK_TYPE
            ):
                already_linked = True
                break

        if already_linked:
            audit["links"]["already_present"] += 1
            continue

        if DRY_RUN:
            print(
                f"[DRY RUN] {issue_a} <-> {issue_b}: "
                f"would create {LINK_TYPE}"
            )
            audit["links"]["created"] += 1
            continue

        jira_request(
            "POST",
            "/rest/api/3/issueLink",
            json={
                "type": {"name": LINK_TYPE},
                "inwardIssue": {"key": issue_a},
                "outwardIssue": {"key": issue_b}
            }
        )

        audit["links"]["created"] += 1
        print(f"[LINKED] {issue_a} <-> {issue_b}")

    except Exception as error:
        audit["links"]["failed"].append({
            "source_a": source_a,
            "source_b": source_b,
            "issue_a": issue_a,
            "issue_b": issue_b,
            "error": str(error)
        })

    save_audit(audit)


# --------------------------------------------------
# FINAL REPORT
# --------------------------------------------------

audit["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
save_audit(audit)

print("\n========== JIRA IMPORT REPORT ==========")
print("Mode:", "DRY RUN" if DRY_RUN else "EXECUTION")
print("Issues label-verified:", audit["issues_checked"])

print("\nCOMMENTS")
print("Expected:", audit["comments"]["expected"])
print("Created / planned:", audit["comments"]["created"])
print("Already present:", audit["comments"]["already_present"])
print("Failed:", len(audit["comments"]["failed"]))

print("\nRELATIONSHIPS")
print("Expected:", audit["links"]["expected"])
print("Created / planned:", audit["links"]["created"])
print("Already present:", audit["links"]["already_present"])
print("Failed:", len(audit["links"]["failed"]))

print("\nLabel verification failures:", len(audit["label_failures"]))
print("Audit file:", AUDIT_FILE)
