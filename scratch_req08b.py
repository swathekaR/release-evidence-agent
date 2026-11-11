
"""Fetch REQ-08 queue adapter evidence records."""
import sys
sys.path.insert(0, r"c:\YellowNetworksAssessment\ReleaseAgent")

from Jira_tools import get_issue, get_issue_comments

# TYN-76 is REC-9635 (linked directly from TYN-342)
# TYN-304 is REC-4925 (queue adapter: atlas-assistant R2.4)

for key in ["TYN-76", "TYN-304"]:
    issue = get_issue(key)
    comments = get_issue_comments(key)
    print(f"\n=== {key}: {issue.get('summary')} ===")
    print("DESC:", issue.get("description","")[:600])
    for c in comments:
        body = c.get("body","").strip()
        if body:
            print("  COMMENT:", body)
