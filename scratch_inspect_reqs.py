
import json
import sys
sys.path.insert(0, r"c:\YellowNetworksAssessment\ReleaseAgent")

from Jira_tools import search_issues, get_issue, get_linked_issues, get_issue_comments

jql = 'project = "TYN" AND labels = "tyn-release-assessment-v2" AND labels = "kind-requirement" ORDER BY key ASC'
results = search_issues(jql, max_results=50)
print(f"Found {len(results)} requirements\n")

for rec in results:
    issue_key = rec["issue_key"]
    # Fetch full issue details (description lives here)
    full = get_issue(issue_key)
    summary = full.get("summary", "")
    description = full.get("description", "")
    status = full.get("status", "")
    labels = full.get("labels", [])

    # Fetch linked issue keys
    linked = get_linked_issues(issue_key)

    print(f"{'='*65}")
    print(f"KEY:     {issue_key}")
    print(f"SUMMARY: {summary}")
    print(f"STATUS:  {status}")
    print(f"LABELS:  {', '.join(labels)}")
    print(f"LINKED:  {linked}")
    print(f"DESCRIPTION:\n{description}")
    print()
