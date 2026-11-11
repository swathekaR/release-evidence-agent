
"""Check TYN-360 (linked to every req) and the REQ-08 queue-adapter dependency."""
import sys
sys.path.insert(0, r"c:\YellowNetworksAssessment\ReleaseAgent")

from Jira_tools import get_issue, get_linked_issues, get_issue_comments

# TYN-360 appears linked to every requirement - what is it?
print("=== TYN-360 ===")
issue = get_issue("TYN-360")
print(issue.get("summary"))
print(issue.get("description", "")[:500])
linked = get_linked_issues("TYN-360")
print("Linked:", linked)

# REQ-08: TYN-342 (REC-4076) mentions "linked queue-adapter work"
# Original Links: ["REC-9635"] - find that in Jira
print("\n=== REQ-08 linked issues including queue-adapter ===")
all_linked = get_linked_issues("TYN-48")
print("TYN-48 linked:", all_linked)

# Check if there's a TYN issue for REC-9635 by searching
from Jira_tools import search_issues
results = search_issues(
    'project = "TYN" AND labels = "tyn-release-assessment-v2" AND summary ~ "REC-9635"',
    max_results=5
)
print("Search REC-9635:", results)

results2 = search_issues(
    'project = "TYN" AND labels = "tyn-release-assessment-v2" AND summary ~ "queue"',
    max_results=10
)
print("Search queue:", [(r["issue_key"], r.get("summary","")) for r in results2])
