
"""
Inspect linked evidence for all 12 requirements.
Prints the description and comments for each linked issue.
"""
import json
import sys
sys.path.insert(0, r"c:\YellowNetworksAssessment\ReleaseAgent")

from Jira_tools import get_issue, get_linked_issues, get_issue_comments

# (key, req_id, linked_keys from the earlier scan)
REQUIREMENTS = [
    ("TYN-48",  "REQ-08", ["TYN-342"]),
    ("TYN-53",  "REQ-04", ["TYN-150", "TYN-339", "TYN-267", "TYN-184"]),
    ("TYN-57",  "REQ-10", ["TYN-9"]),
    ("TYN-73",  "REQ-06", ["TYN-180", "TYN-119"]),
    ("TYN-89",  "REQ-01", ["TYN-316", "TYN-130"]),
    ("TYN-143", "REQ-09", ["TYN-105", "TYN-174"]),
    ("TYN-162", "REQ-11", ["TYN-259", "TYN-102"]),
    ("TYN-225", "REQ-03", ["TYN-214", "TYN-26"]),
    ("TYN-263", "REQ-02", ["TYN-306", "TYN-217"]),
    ("TYN-329", "REQ-07", ["TYN-50", "TYN-301", "TYN-396"]),
    ("TYN-352", "REQ-05", ["TYN-224", "TYN-62"]),
    ("TYN-400", "REQ-12", ["TYN-35", "TYN-318"]),
]

# Skip TYN-360 (appears in every req) and TYN-53 linked which we already know

for req_key, req_id, linked_keys in REQUIREMENTS:
    print(f"\n{'#'*70}")
    print(f"# REQUIREMENT: {req_key} ({req_id})")
    print(f"{'#'*70}")
    for linked_key in linked_keys:
        issue = get_issue(linked_key)
        comments = get_issue_comments(linked_key)
        summary = issue.get("summary", "")
        description = issue.get("description", "")
        print(f"\n  --- {linked_key}: {summary} ---")
        print(f"  DESCRIPTION:\n{description}")
        for c in comments:
            body = c.get("body", "")
            if body.strip():
                print(f"  COMMENT: {body}")
        print()
