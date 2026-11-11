
import json
import sys
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

# Reuse the Jira functions already tested in jira_tools.py.
from Jira_tools import (
    search_issues,
    get_issue,
    get_issue_comments,
    get_linked_issues
)

# All 12 deterministic evaluators + release decision engine.
from evaluators import evaluate_all_requirements, EVALUATORS, TARGET as EVAL_TARGET


# --------------------------------------------------
# 1. ASSESSMENT CONFIGURATION
# --------------------------------------------------

TARGET = {
    "release": "R2.4",
    "commit": "b7a91f2",
    "prompt": "p7",
    "environment": "production",
    "service": "atlas-assistant"
}

PROJECT_KEY = "TYN"
DATASET_LABEL = "tyn-release-assessment-v2"


# --------------------------------------------------
# 2. HELPER FUNCTION
# --------------------------------------------------

def to_json(data):
    """Convert Python objects into readable JSON for the LLM."""
    return json.dumps(data, indent=2, ensure_ascii=False)


# --------------------------------------------------
# 3. JIRA TOOLS AVAILABLE TO THE AGENT
# --------------------------------------------------

@tool
def search_requirements() -> str:
    """
    Find all mandatory release requirement records in the
    imported Jira assessment dataset.
    Use this first to discover the requirements.
    """
    jql = (
        f'project = "{PROJECT_KEY}" '
        f'AND labels = "{DATASET_LABEL}" '
        'AND labels = "kind-requirement"'
    )

    results = search_issues(jql, max_results=30)
    return to_json(results)


@tool
def get_issue_details(issue_key: str) -> str:
    """
    Retrieve a Jira issue's summary, description, status,
    labels and linked issue references.
    Use a Jira key such as TYN-53.
    """
    issue = get_issue(issue_key)
    return to_json(issue)


@tool
def get_issue_comments_tool(issue_key: str) -> str:
    """
    Retrieve all comments for a Jira issue.
    Original scenario actor, role and event timestamp
    are preserved inside the comment text.
    """
    comments = get_issue_comments(issue_key)
    return to_json(comments)


@tool
def get_linked_issue_keys_tool(issue_key: str) -> str:
    """
    Find all Jira issue keys linked to a given issue.
    Use this to follow requirement-to-evidence relationships.
    """
    linked_keys = get_linked_issues(issue_key)
    return to_json(linked_keys)


@tool
def investigate_requirement(issue_key: str) -> str:
    """
    Investigate one requirement by retrieving its details,
    linked issues, and comments on those linked issues.
    This is the main tool for gathering requirement evidence.
    """
    requirement = get_issue(issue_key)
    linked_keys = get_linked_issues(issue_key)

    evidence = []

    # Bound the investigation to avoid excessive Jira requests.
    for linked_key in linked_keys[:20]:
        linked_issue = get_issue(linked_key)
        comments = get_issue_comments(linked_key)

        description = linked_issue.get("description", "")
        record_type = "unknown"

        for line in description.splitlines():
            if line.startswith("Record Type:"):
                record_type = line.split(":", 1)[1].strip()
                break

        evidence.append({
            "issue_key": linked_key,
            "record_type": record_type,
            "summary": linked_issue.get("summary"),
            "description": description,
            "comments": [
                comment["body"] for comment in comments
            ]
        })

    return to_json({
        "target": TARGET,
        "requirement": requirement,
        "linked_records": evidence
    })

# --------------------------------------------------
# 3B. DETERMINISTIC REQ-04 EVALUATION
# --------------------------------------------------



@tool
def evaluate_latency_requirement(issue_key: str) -> str:
    """
    Evaluate REQ-04 using both Jira issue descriptions
    and comments. Jira workflow status is not proof.
    """

    requirement = get_issue(issue_key)
    requirement_description = requirement.get("description", "")

    threshold_match = re.search(
        r"at most\s+([0-9]+(?:\.[0-9]+)?)\s*seconds",
        requirement_description,
        re.IGNORECASE
    )

    if not threshold_match:
        return to_json({
            "decision": "INSUFFICIENT_EVIDENCE",
            "reason": "Could not extract latency threshold."
        })

    threshold = float(threshold_match.group(1))
    linked_keys = get_linked_issues(issue_key)

    applicable = []
    excluded = []

    for linked_key in linked_keys:
        record = get_issue(linked_key)
        comments = get_issue_comments(linked_key)

        summary = record.get("summary", "")
        description = record.get("description", "")

        if not summary.startswith("[REC-"):
            excluded.append({
                "issue_key": linked_key,
                "reason": "Not an evidence record"
            })
            continue

        # Combine issue description and comment bodies.
        # Original event metadata remains intact.
        comment_text = "\n".join(
            comment.get("body", "")
            for comment in comments
        )

        evidence_text = description + "\n" + comment_text

        def extract(pattern):
            match = re.search(pattern, evidence_text, re.IGNORECASE)
            return match.group(1).strip() if match else None

        release = extract(r"\brelease\s*[:=]?\s*(R\d+(?:\.\d+)?)")
        commit = extract(r"\bcommit\s*[:=]?\s*([a-f0-9]+)")
        service = extract(r"\bservice\s*[:=]?\s*([a-z0-9_-]+)")
        environment = extract(r"\benvironment\s*[:=]?\s*([a-z0-9_-]+)")
        prompt = extract(r"\bprompt\s*[:=]?\s*([a-z0-9_-]+)")
        latency_match = re.search(
            r"measured\s+p95\s+latency\s+"
            r"([0-9]+(?:\.[0-9]+)?)\s*seconds",
            evidence_text,
            re.IGNORECASE
        )

        latency = (
            float(latency_match.group(1))
            if latency_match else None
        )

        evidence_details = {
            "issue_key": linked_key,
            "summary": summary,
            "release": release,
            "commit": commit,
            "service": service,
            "environment": environment,
            "prompt": prompt,
            "p95_latency_seconds": latency,
            "jira_status": record.get("status")
        }

        # Validate the complete target configuration.
        matches_target = (
            release == TARGET["release"]
            and commit == TARGET["commit"]
            and service == TARGET["service"]
            and environment == TARGET["environment"]
            and prompt == TARGET["prompt"]
        )

        evidence_details["matches_target"] = matches_target

        if not matches_target:
            mismatches = []
            for field, target_value in TARGET.items():
                actual_value = evidence_details.get(field)

                if actual_value != target_value:
                    mismatches.append({
                        "field": field,
                        "actual": actual_value,
                        "expected": target_value
                    })

            excluded.append({
                **evidence_details,
                "reason": "Target configuration mismatch",
                "mismatched_fields": mismatches
            })
            continue

        if latency is None:
            excluded.append({**evidence_details, "reason": "No readable p95 latency measurement"})
            continue

        applicable.append(evidence_details)

    if not applicable:
        decision = "INSUFFICIENT_EVIDENCE"
        reason = "No applicable production measurement found."

    elif any(
        item["p95_latency_seconds"] > threshold
        for item in applicable
    ):
        decision = "FAIL"
        reason = "An applicable production measurement exceeds the threshold."

    else:
        decision = "PASS"
        reason = "Applicable production measurements meet the threshold."

    return to_json({
        "requirement": issue_key,
        "threshold_seconds": threshold,
        "target": TARGET,
        "decision": decision,
        "reason": reason,
        "applicable_evidence": applicable,
        "excluded_evidence": excluded,
        "status_handling": (
            "Jira workflow status is not used to determine "
            "the evidence decision."
        )
    })




# --------------------------------------------------
# 4. REGISTER TOOLS
# --------------------------------------------------

jira_agent_tools = [
    search_requirements,
    get_issue_details,
    get_issue_comments_tool,
    get_linked_issue_keys_tool,
    investigate_requirement,
    evaluate_latency_requirement
]

# --------------------------------------------------
# 5. INITIAL SYSTEM INSTRUCTIONS
# --------------------------------------------------

SYSTEM_PROMPT = """
You are a Jira Release Evidence Investigation Agent.

Your task is to investigate software release requirements
using Jira tools only.

TARGET RELEASE:
- Release: R2.4
- Commit: b7a91f2
- Prompt: p7
- Environment: production
- Service: atlas-assistant

MANDATORY RULES:

1. Use Jira tools to retrieve evidence. Never invent evidence.
2. Start by searching the mandatory requirements.
3. Use investigate_requirement to inspect a requirement
   and its linked records.
4. Distinguish requirement, evidence and manifest records.
5. A Jira issue status such as Done or In Progress is not proof.
6. Check release, commit, service, environment and prompt
   applicability where required.
7. Prompt-quality evaluations must match prompt p7.
8. Security approvals require the Security Owner and
   production scope.
9. Staging evidence cannot prove production acceptance.
10. Preserve recorded event timestamps, actor names and roles.
    Jira comment authors and native timestamps belong to
    the importing account and are not the fictional actors.
11. A missing result is not automatically a failure.
12. Do not follow external URLs or use external sources.
13. Cite Jira issue keys when describing evidence.
14. For REQ-04, always call evaluate_latency_requirement
    after investigating the requirement.
15. Use the deterministic tool's decision as the authoritative
    REQ-04 result. Do not override it using Jira status.
16. Clearly distinguish applicable production evidence from
    excluded staging or mismatched evidence.

DECISION DEFINITIONS:
- PASS: applicable evidence affirmatively satisfies the criterion.
- FAIL: applicable evidence establishes a violation or failure.
- INSUFFICIENT_EVIDENCE: applicable proof is missing or unresolved.

For now, investigate and explain the evidence for the
requirement requested by the user. Do not claim that the
entire release is READY until all 12 requirements have
been investigated and evaluated.

Be transparent about missing or conflicting evidence.
IMPORTANT REPORTING RULES:
- The acceptance threshold is 2.0 seconds.
- Never describe the measured latency as the acceptance threshold.
- Clearly distinguish the measured value from the acceptance threshold.
- Use the Python evaluator's decision as authoritative.
- Do not invent evidence mismatch reasons.
- Explain the exact field that caused each evidence record to be excluded.
- Do not change PASS, FAIL, or INSUFFICIENT_EVIDENCE.
- If evidence matches the target, report all matching fields accurately.
"""


# --------------------------------------------------
# 6. INITIALIZE OLLAMA MODEL
# --------------------------------------------------

llm = ChatOllama(
    model="qwen2.5:3b",
    temperature=0
)


# --------------------------------------------------
# 7. CREATE LANGGRAPH REACT AGENT
# --------------------------------------------------

agent = create_react_agent(
    model=llm,
    tools=jira_agent_tools,
    state_modifier=SYSTEM_PROMPT
)

def run_requirement_investigation(
    issue_key: str,
    question: str,
    eval_result: dict
) -> dict:

    import json

    start_time = time.time()

    # 1. Get the evaluator's authoritative classification
    verified_decision = eval_result.get(
        "decision", "INSUFFICIENT_EVIDENCE"
    )
    verified_reason = eval_result.get(
        "reason", "No evaluator reason provided."
    )

    applicable_evidence = eval_result.get(
        "applicable_evidence", []
    )
    excluded_evidence = eval_result.get(
        "excluded_evidence", []
    )

    # 2. Build the allowed Jira issue-key list
    allowed_keys = {
        item["issue_key"]
        for item in applicable_evidence + excluded_evidence
        if item.get("issue_key")
    }

    # 3. Retrieve Jira evidence using the existing Jira tool
    jira_result = investigate_requirement.invoke({
        "issue_key": issue_key
    })

    # Ensure jira_result is parsed as a dictionary if returned as a JSON string
    if isinstance(jira_result, str):
        try:
            jira_result = json.loads(jira_result)
        except Exception:
            jira_result = {}

    # 4. Keep only evaluator-classified evidence records
    linked_records = jira_result.get("linked_records", []) if isinstance(jira_result, dict) else []

    filtered_records = [
        record
        for record in linked_records
        if record.get("issue_key") in allowed_keys
    ]

    # 5. Send only verified evidence to the LLM
    evidence_context = {
        "applicable_evidence": applicable_evidence,
        "excluded_evidence": excluded_evidence,
        "filtered_jira_records": filtered_records
    }

    user_prompt = f"""
You are an AI evidence explanation assistant.

Requirement: {issue_key}
User question: {question}

Authoritative Python evaluator result:
Decision: {verified_decision}
Reason: {verified_reason}

Verified evidence supplied by Python:
{json.dumps(evidence_context, indent=2, default=str)}

Instructions:
1. Explain only the evidence supplied above.
2. Do not introduce any other Jira issue.
3. Keep applicable and excluded evidence separate.
4. Explain configuration mismatches exactly as supplied.
5. Explain test results using the Jira descriptions and comments.
6. Explain explicit supersession when supported by the comments.
7. Do not invent thresholds, test results, actors, or timestamps.
8. If a detail is unavailable, state that it is not established.
9. Do not change the evaluator's classifications.
10. Do not independently produce a compliance decision.
11. Do not recommend investigating another requirement.

Provide a concise, factual investigation summary.
"""

    # 6. Generate the explanation
    response = llm.invoke(user_prompt)
    if not response.content or not str(response.content).strip():
        raise RuntimeError(
        "The LLM returned an empty investigation summary."
    )

    elapsed = round(time.time() - start_time, 3)

    return {
        "requirement_key": issue_key,
        "investigation_summary": response.content,
        "execution_time_seconds": elapsed,
        "model": "qwen2.5:3b",
        "agent_invoked": True
    }
def _fmt_decision(d: str) -> str:
    """Add an emoji indicator to a decision string."""
    return {"PASS": "✅ PASS", "FAIL": "❌ FAIL",
            "INSUFFICIENT_EVIDENCE": "⚠️  INSUFFICIENT_EVIDENCE"}.get(d, d)


def _build_full_report(release_result: dict, elapsed: float) -> str:
    """Format the complete release assessment as a human-readable TXT report."""
    lines = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("=" * 65)
    lines.append("JIRA RELEASE EVIDENCE ASSESSMENT REPORT")
    lines.append("=" * 65)
    lines.append(f"Generated : {ts}")
    lines.append(f"Release   : {release_result['release']}")
    lines.append(f"Duration  : {elapsed:.1f}s")
    lines.append("")

    # Target configuration
    lines.append("TARGET CONFIGURATION")
    lines.append("-" * 30)
    for k, v in release_result["target"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    # Overall decision banner
    overall = release_result["overall_decision"]
    lines.append("=" * 65)
    lines.append(f"OVERALL DECISION: {overall}")
    lines.append(release_result["overall_reason"])
    lines.append("=" * 65)
    lines.append("")

    # Summary table
    lines.append("REQUIREMENT SUMMARY")
    lines.append("-" * 65)
    lines.append(f"  {'Req':8}  {'Jira':10}  Decision")
    lines.append(f"  {'-'*8}  {'-'*10}  {'-'*25}")
    req_map = {req_id: jira_key for req_id, jira_key, _ in EVALUATORS}
    for req_id, decision in release_result["decisions"].items():
        jk = req_map.get(req_id, "")
        lines.append(f"  {req_id:8}  {jk:10}  {_fmt_decision(decision)}")
    lines.append("")

    # Per-requirement detail
    lines.append("=" * 65)
    lines.append("DETAILED REQUIREMENT FINDINGS")
    lines.append("=" * 65)

    for req_id, jira_key, _ in EVALUATORS:
        result = release_result["requirement_results"].get(req_id, {})
        lines.append("")
        lines.append(f"{'─'*65}")
        lines.append(
            f"{req_id}  ({jira_key})  —  "
            f"{_fmt_decision(result.get('decision', '?'))}"
        )
        lines.append(f"Criterion : {result.get('criterion', '')}")
        lines.append(f"Decision  : {result.get('decision', '')}")
        lines.append(f"Reason    : {result.get('reason', '')}")

        applicable = result.get("applicable_evidence", [])
        excluded   = result.get("excluded_evidence", [])

        if applicable:
            lines.append(f"\n  Applicable evidence ({len(applicable)} record(s)):")
            for ev in applicable:
                lines.append(f"    • {ev['issue_key']} — {ev.get('summary','')}")
                for field in ("release", "commit", "service", "environment", "prompt"):
                    if ev.get(field):
                        lines.append(f"        {field}: {ev[field]}")
                for extra_key in (
                    "p95_latency_seconds", "mean_cost_usd",
                    "quality_percent", "passed", "total",
                ):
                    if ev.get(extra_key) is not None:
                        lines.append(f"        {extra_key}: {ev[extra_key]}")

        if excluded:
            lines.append(f"\n  Excluded records ({len(excluded)} record(s)):")
            for ex in excluded:
                lines.append(
                    f"    • {ex['issue_key']} — "
                    f"{ex.get('reason', 'excluded')}"
                )
                for mm in ex.get("mismatched_fields", []):
                    lines.append(
                        f"        {mm['field']}: "
                        f"actual={mm['actual']}, expected={mm['expected']}"
                    )

    lines.append("")
    lines.append("─" * 65)
    lines.append(
        "Note: Jira workflow status is not used to determine "
        "evidence acceptance."
    )
    lines.append("─" * 65)

    return "\n".join(lines)


def run_agent(question: str = "Assess release R2.4"):
    """
    Run the full 12-requirement deterministic release assessment.
    Steps:
      1. Search Jira for mandatory requirements (via LangGraph tool).
      2. Evaluate all 12 requirements deterministically.
      3. Compute overall release decision.
      4. Generate and save TXT + JSON reports.
    """
    print("\nStarting Jira Release Evidence Agent...")
    print(f"Question : {question}")
    print(f"Target   : {EVAL_TARGET}")

    start = time.time()

    # ------------------------------------------------------------------
    # Step 1: Search requirements via the registered LangGraph tool
    # ------------------------------------------------------------------
    print("\n[STEP 1] Searching Jira requirements...")
    requirements_result = search_requirements.invoke({})
    req_list = json.loads(requirements_result)
    print(f"         Found {len(req_list)} requirement records.")

    # ------------------------------------------------------------------
    # Step 2: Run all 12 deterministic evaluators
    # ------------------------------------------------------------------
    print("\n[STEP 2] Evaluating all 12 requirements...")
    release_result = evaluate_all_requirements()

    elapsed = time.time() - start

    # ------------------------------------------------------------------
    # Step 2A: Build investigation trace and execution metrics
    # ------------------------------------------------------------------
    requirement_results = release_result.get("requirement_results", {})
    investigation_trace = []

    for req_id, result in requirement_results.items():
        applicable = result.get("applicable_evidence", [])
        excluded = result.get("excluded_evidence", [])

        investigation_trace.append({
            "requirement_id": req_id,
            "requirement_jira_key": result.get("requirement"),
            "decision": result.get("decision"),
            "applicable_evidence_issue_keys": [
                item.get("issue_key") for item in applicable
                if item.get("issue_key")
            ],
            "excluded_evidence_issue_keys": [
                item.get("issue_key") for item in excluded
                if item.get("issue_key")
            ]
        })

    release_result["investigation_trace"] = investigation_trace

    release_result["runtime_metrics"] = {
        "total_execution_seconds": round(elapsed, 3),
        "requirements_discovered": len(req_list),
        "requirements_evaluated": len(release_result.get("decisions", {})),
        "evaluation_mode": "deterministic",
        "jira_requirements_search_completed": True
    }

    release_result["model_usage"] = {
        "status": "not_invoked",
        "reason": (
            "Final requirement decisions were produced by deterministic "
            "evaluators. The initialized LangGraph LLM agent was not invoked."
        ),
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None
    }

    # ------------------------------------------------------------------
    # Step 3: Display per-requirement results
    # ------------------------------------------------------------------
    print("\n========== REQUIREMENT DECISIONS ==========")
    for req_id, decision in release_result["decisions"].items():
        print(f"  {req_id}: {_fmt_decision(decision)}")

    # ------------------------------------------------------------------
    # Step 4: Display overall decision
    # ------------------------------------------------------------------
    print("\n========== OVERALL RELEASE DECISION ==========")
    print(f"  {release_result['overall_decision']}")
    print(f"  {release_result['overall_reason']}")

    # ------------------------------------------------------------------
    # Step 5: Build human-readable report
    # ------------------------------------------------------------------
    print("\n[STEP 5] Generating full report...")
    report_text = _build_full_report(release_result, elapsed)

    report_text += "\n\nINVESTIGATION TRACE\n"
    report_text += "=" * 65 + "\n"

    for item in release_result["investigation_trace"]:
        report_text += (
            f"{item['requirement_id']} | "
            f"{item['decision']} | "
            f"Requirement: {item['requirement_jira_key']} | "
            f"Evidence: {', '.join(item['applicable_evidence_issue_keys']) or 'None'} | "
            f"Excluded: {', '.join(item['excluded_evidence_issue_keys']) or 'None'}\n"
        )

    report_text += "\nRUNTIME METRICS\n"
    report_text += "=" * 65 + "\n"
    report_text += json.dumps(
        release_result["runtime_metrics"], indent=2
    )

    report_text += "\n\nMODEL USAGE\n"
    report_text += "=" * 65 + "\n"
    report_text += json.dumps(
        release_result["model_usage"], indent=2
    )

    # ------------------------------------------------------------------
    # Step 6: Save reports
    # ------------------------------------------------------------------
    reports_folder = Path("reports")
    reports_folder.mkdir(exist_ok=True)

    ts_safe = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    txt_path  = reports_folder / f"release_R2.4_{ts_safe}.txt"
    json_path = reports_folder / f"release_R2.4_{ts_safe}.json"

    txt_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(release_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n========== REPORT FILES SAVED ==========")
    print(f"  Text : {txt_path.resolve()}")
    print(f"  JSON : {json_path.resolve()}")

    # ------------------------------------------------------------------
    # Step 7: Print report to console
    # ------------------------------------------------------------------
    print("\n" + report_text)

    return release_result


# --------------------------------------------------
# 9. APPLICATION ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    try:
        run_agent()
    except Exception as error:
        print("\nAgent execution failed:")
        print(str(error))
        sys.exit(1)
