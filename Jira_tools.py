
import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "TYN")

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    raise ValueError(
        "Missing Jira configuration. Check JIRA_BASE_URL, "
        "JIRA_EMAIL and JIRA_API_TOKEN in your .env file."
    )

session = requests.Session()
session.auth = (JIRA_EMAIL, JIRA_API_TOKEN)
session.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json"
})


def jira_get(endpoint, params=None):
    """Make an authenticated, read-only Jira API request."""
    url = f"{JIRA_BASE_URL}{endpoint}"

    response = session.get(
        url,
        params=params,
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            f"Jira API error {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


def adf_to_text(value):
    """Convert Jira's Atlassian Document Format into readable text."""
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "\n".join(
            filter(None, (adf_to_text(item) for item in value))
        )

    if isinstance(value, dict):
        text = value.get("text", "")
        children = adf_to_text(value.get("content", []))

        if text and children:
            return text + children
        return text or children

    return ""


def search_issues(jql, max_results=100):
    """
    Search Jira using JQL.
    Returns a bounded list of matching issues.
    """
    if not jql or not isinstance(jql, str):
        raise ValueError("A valid JQL query is required.")

    max_results = max(1, min(int(max_results), 100))

    all_issues = []
    next_page_token = None

    while len(all_issues) < max_results:
        params = {
            "jql": jql,
            "maxResults": min(50, max_results - len(all_issues)),
            "fields": "summary,status,issuetype,labels"
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        data = jira_get("/rest/api/3/search/jql", params)

        all_issues.extend(data.get("issues", []))

        next_page_token = data.get("nextPageToken")

        if not next_page_token:
            break

    results = []

    for issue in all_issues[:max_results]:
        fields = issue.get("fields", {})

        results.append({
            "issue_key": issue["key"],
            "summary": fields.get("summary"),
            "issue_type": fields.get("issuetype", {}).get("name"),
            "status": fields.get("status", {}).get("name"),
            "labels": fields.get("labels", [])
        })

    return results


def get_issue(issue_key):
    """Retrieve one Jira issue and its linked issue references."""
    if not issue_key:
        raise ValueError("Issue key is required.")

    data = jira_get(
        f"/rest/api/3/issue/{issue_key}",
        {
            "fields": (
                "summary,description,status,issuetype,"
                "labels,issuelinks,created,updated"
            )
        }
    )

    fields = data.get("fields", {})
    links = []

    for link in fields.get("issuelinks", []):
        linked_issue = (
            link.get("outwardIssue")
            or link.get("inwardIssue")
        )

        if linked_issue:
            links.append({
                "issue_key": linked_issue.get("key"),
                "relationship": link.get("type", {}).get("name")
            })

    return {
        "issue_key": data.get("key"),
        "summary": fields.get("summary"),
        "description": adf_to_text(fields.get("description")),
        "issue_type": fields.get("issuetype", {}).get("name"),
        "status": fields.get("status", {}).get("name"),
        "labels": fields.get("labels", []),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "linked_issues": links
    }


def get_issue_comments(issue_key):
    """Retrieve all comments from one Jira issue."""
    if not issue_key:
        raise ValueError("Issue key is required.")

    comments = []
    start_at = 0
    page_size = 100

    while True:
        data = jira_get(
            f"/rest/api/3/issue/{issue_key}/comment",
            {
                "startAt": start_at,
                "maxResults": page_size
            }
        )

        page_comments = data.get("comments", [])

        for comment in page_comments:
            comments.append({
                "jira_author": (
                    comment.get("author", {}).get("displayName")
                ),
                "jira_created": comment.get("created"),
                "body": adf_to_text(comment.get("body"))
            })

        start_at += len(page_comments)

        if start_at >= data.get("total", 0) or not page_comments:
            break

    return comments


def get_linked_issues(issue_key):
    """Retrieve the issue and return its linked issue keys."""
    issue = get_issue(issue_key)

    return [
        link["issue_key"]
        for link in issue["linked_issues"]
    ]

def classify_linked_records(issue_keys):
    """
    Retrieve linked Jira issues and keep only evidence records.
    """
    evidence_records = []

    for issue_key in issue_keys:
        issue = get_issue(issue_key)
        description = issue.get("description", "")

        record_type = None

        for line in description.splitlines():
            if line.startswith("Record Type:"):
                record_type = line.split(":", 1)[1].strip().lower()
                break

        if record_type == "evidence":
            comments = get_issue_comments(issue_key)

            evidence_records.append({
                "issue_key": issue_key,
                "summary": issue["summary"],
                "description": description,
                "comments": comments
            })

    return evidence_records



if __name__ == "__main__":
    print("Testing Jira investigation tools...")
    jql = (
    f'project = "{JIRA_PROJECT_KEY}" '
    'AND labels = "tyn-release-assessment-v2" '
    'AND labels = "kind-requirement"'
)

    requirements = search_issues(jql)

    print(f"\nRequirements found: {len(requirements)}")

    for requirement in requirements:
        print(
            requirement["issue_key"],
            "-",
            requirement["summary"]
        )

    
    print("\n========== EVIDENCE CLASSIFICATION ==========")

    linked_keys = get_linked_issues("TYN-53")
    evidence_records = classify_linked_records(linked_keys)

    print("Total linked issues:", len(linked_keys))
    print("Evidence records:", len(evidence_records))

    for record in evidence_records:
        print("\n", record["issue_key"], "-", record["summary"])
        print("Comments:", len(record["comments"]))

        
# def classify_linked_records(issue_keys):
#     """
#     Separate evidence records from requirements and manifest records.
#     Does not decide PASS or FAIL.
#     """
#     evidence_records = []

#     for issue_key in issue_keys:
#         issue = get_issue(issue_key)

#         description = issue.get("description", "")

#         record_type = None

#         for line in description.splitlines():
#             if line.startswith("Record Type:"):
#                 record_type = line.split(":", 1)[1].strip().lower()
#                 break

#         if record_type == "evidence":
#             comments = get_issue_comments(issue_key)

#             evidence_records.append({
#                 "issue_key": issue_key,
#                 "summary": issue["summary"],
#                 "description": description,
#                 "comments": comments
#             })

#     return evidence_records


