
import os
import json
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

JIRA_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

# Validate configuration
if not all([JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
    raise ValueError("Missing Jira configuration. Check your .env file.")

JIRA_URL = JIRA_URL.rstrip("/")


auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)

url = f"{JIRA_URL}/rest/api/3/search/jql"

mapping = {}
missing = []
duplicates = []
next_page_token = None

while True:

    params = {
        "jql": "project = TYN",
        "maxResults": 100,
        "fields": "summary,labels"
    }

    if next_page_token:
        params["nextPageToken"] = next_page_token

    response = requests.get(
        url,
        params=params,
        auth=auth,
        headers={"Accept": "application/json"}
    )

    response.raise_for_status()
    data = response.json()

    for issue in data.get("issues", []):

        issue_key = issue["key"]
        fields = issue.get("fields", {})
        labels = fields.get("labels", [])

        # Find the original source ID label
        source_labels = [
            label for label in labels
            if label.startswith("source-")
        ]

        if len(source_labels) == 0:
            missing.append(issue_key)
            continue

        if len(source_labels) > 1:
            duplicates.append({
                "issue_key": issue_key,
                "labels": source_labels
            })
            continue

        source_id = source_labels[0].replace("source-", "", 1)

        if source_id in mapping:
            duplicates.append({
                "source_id": source_id,
                "issue_keys": [mapping[source_id], issue_key]
            })
            continue

        mapping[source_id] = issue_key

    next_page_token = data.get("nextPageToken")

    if not next_page_token:
        break

# Save mapping locally
with open("source_issue_mapping.json", "w") as f:
    json.dump(mapping, f, indent=4)

print("\n========== MAPPING REPORT ==========")
print("Mapped source IDs:", len(mapping))
print("Issues without source labels:", len(missing))
print("Duplicate mappings:", len(duplicates))

print("\nSample mappings:")

for source_id, issue_key in list(mapping.items())[:10]:
    print(source_id, "->", issue_key)

print("\nMissing issue keys:", missing[:20])
print("\nDuplicate mappings:", duplicates[:10])

print("\nMapping saved to source_issue_mapping.json")
