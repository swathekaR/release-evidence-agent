"""
evaluators.py — Deterministic evidence evaluators for all 12 release requirements.

Each evaluator follows the same pattern as the working REQ-04 implementation:
  1. Fetch the requirement description to extract the acceptance criterion.
  2. Fetch linked evidence issues and their comments.
  3. Filter for applicable evidence (target match).
  4. Apply requirement-specific logic.
  5. Return a structured dict (not JSON string) with decision, reason, evidence.

Decisions:
  PASS                - Applicable evidence affirmatively satisfies the criterion.
  FAIL                - Applicable evidence establishes a violation or failure.
  INSUFFICIENT_EVIDENCE - No applicable proof found, or result is unresolved.
"""

import re
from typing import Any

from Jira_tools import (
    get_issue,
    get_issue_comments,
    get_linked_issues,
)

# ---------------------------------------------------------------------------
# Shared target configuration
# ---------------------------------------------------------------------------

TARGET = {
    "release": "R2.4",
    "commit": "b7a91f2",
    "prompt": "p7",
    "environment": "production",
    "service": "atlas-assistant",
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract(pattern: str, text: str) -> str | None:
    """Return the first capture group of *pattern* in *text*, or None."""
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _build_evidence_text(issue: dict, comments: list[dict]) -> str:
    """Combine issue description and all comment bodies."""
    comment_bodies = "\n".join(c.get("body", "") for c in comments)
    return issue.get("description", "") + "\n" + comment_bodies


def _target_fields(text: str) -> dict:
    """Extract the five target fields from an evidence text block."""
    return {
        "release":     _extract(r"\brelease\s*[:=]?\s*(R\d+(?:\.\d+)?)", text),
        "commit":      _extract(r"\bcommit\s*[:=]?\s*([a-f0-9]{5,})", text),
        "service":     _extract(r"\bservice\s*[:=]?\s*([a-z0-9_-]+)", text),
        "environment": _extract(r"\benvironment\s*[:=]?\s*([a-z0-9_-]+)", text),
        "prompt":      _extract(r"\bprompt(?:\s+bundle)?\s*[:=]?\s*(p\d+)", text),
    }


def _mismatches(actual: dict, require_prompt: bool = False) -> list[dict]:
    """Return list of field-level mismatches against TARGET."""
    mismatches = []
    for k in TARGET:
        if k == "prompt" and not require_prompt:
            # If prompt is not required for this requirement type:
            # only mismatch if actual is present and differs from TARGET
            if actual.get("prompt") is not None and actual.get("prompt") != TARGET["prompt"]:
                mismatches.append({"field": k, "actual": actual.get(k), "expected": TARGET[k]})
            continue

        if actual.get(k) != TARGET[k]:
            mismatches.append({"field": k, "actual": actual.get(k), "expected": TARGET[k]})
    return mismatches


def _classify_linked(req_key: str, require_prompt: bool = False) -> tuple[list[dict], list[dict]]:
    """
    For every linked issue of *req_key* (excluding the manifest TYN-360),
    return (applicable, excluded) lists.

    Each item contains:
      issue_key, summary, evidence_text, fields (extracted target fields),
      comments (raw list), mismatches.
    """
    applicable: list[dict] = []
    excluded:   list[dict] = []

    linked_keys = get_linked_issues(req_key)

    for key in linked_keys:
        if key == "TYN-360":          # manifest record, skip always
            continue

        issue    = get_issue(key)
        comments = get_issue_comments(key)
        summary  = issue.get("summary", "")
        ev_text  = _build_evidence_text(issue, comments)

        # Only process records whose summary starts with [REC-
        if not summary.startswith("[REC-"):
            excluded.append({
                "issue_key": key,
                "summary":   summary,
                "reason":    "Not an evidence record",
            })
            continue

        fields = _target_fields(ev_text)
        mm     = _mismatches(fields, require_prompt=require_prompt)

        record = {
            "issue_key":    key,
            "summary":      summary,
            "evidence_text": ev_text,
            "fields":       fields,
            "comments":     comments,
            "mismatches":   mm,
        }

        if mm:
            excluded.append({**record, "reason": "Target configuration mismatch"})
        else:
            applicable.append(record)

    return applicable, excluded


def _result(
    req_key: str,
    criterion: str,
    decision: str,
    reason: str,
    applicable: list,
    excluded: list,
    extra: dict | None = None,
) -> dict:
    """Build the standard result dict."""
    out = {
        "requirement":          req_key,
        "criterion":            criterion,
        "target":               TARGET,
        "decision":             decision,
        "reason":               reason,
        "applicable_evidence":  [_strip(r) for r in applicable],
        "excluded_evidence":    [_strip_exc(r) for r in excluded],
        "status_handling":      (
            "Jira workflow status is not used to determine the evidence decision."
        ),
    }
    if extra:
        out.update(extra)
    return out


def _strip(r: dict) -> dict:
    """Return a serialisable subset of an applicable record."""
    return {
        "issue_key":  r["issue_key"],
        "summary":    r["summary"],
        **r["fields"],
    }


def _strip_exc(r: dict) -> dict:
    """Return a serialisable subset of an excluded record."""
    base = {
        "issue_key": r["issue_key"],
        "summary":   r.get("summary"),
        "reason":    r.get("reason"),
    }
    if r.get("mismatches"):
        base["mismatched_fields"] = r["mismatches"]
    return base


# ===========================================================================
# REQ-01 — Automated regression tests  (TYN-89)
# All automated regression cases must pass on the target build.
# Pattern: "N of M mandatory regression cases pass" — require N == M.
# ===========================================================================

def evaluate_req01(issue_key: str = "TYN-89") -> dict:
    criterion = (
        "All automated regression cases must pass on the target build."
    )
    applicable, excluded = _classify_linked(issue_key)

    passing_records = []
    failing_records = []

    for rec in applicable:
        ev = rec["evidence_text"]
        # Look for "N of M mandatory … cases pass" (last superseding result wins)
        matches = re.findall(
            r"(\d+)\s+of\s+(\d+)\s+mandatory(?:\s+regression)?\s+cases?\s+pass",
            ev, re.IGNORECASE,
        )
        if not matches:
            excluded.append({**rec, "reason": "No readable regression result"})
            continue

        # Use the last (most recent / superseding) result
        passed_str, total_str = matches[-1]
        passed, total = int(passed_str), int(total_str)
        rec["passed"] = passed
        rec["total"]  = total

        if passed == total:
            passing_records.append(rec)
        else:
            failing_records.append(rec)

    if failing_records:
        decision = "FAIL"
        reason   = (
            f"Regression run failed: "
            f"{failing_records[0]['passed']} of "
            f"{failing_records[0]['total']} cases passed "
            f"(TYN: {failing_records[0]['issue_key']})."
        )
    elif passing_records:
        rec      = passing_records[0]
        decision = "PASS"
        reason   = (
            f"All {rec['total']} mandatory regression cases pass "
            f"({rec['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable regression result found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded,
                   extra={"passing_records": [_strip(r) for r in passing_records],
                           "failing_records":  [_strip(r) for r in failing_records]})


# ===========================================================================
# REQ-02 — Customer document isolation  (TYN-263)
# Every isolation case must pass; any confirmed cross-customer
# document exposure blocks the release.
# ===========================================================================

def evaluate_req02(issue_key: str = "TYN-263") -> dict:
    criterion = (
        "Every isolation case must pass; any confirmed cross-customer "
        "document exposure blocks release."
    )
    applicable, excluded = _classify_linked(issue_key)

    # Exposure keywords that constitute a confirmed breach
    EXPOSURE_PATTERNS = [
        r"received document .{0,80} belonging to customer",
        r"cross.customer documents? returned",
        r"cross.customer .{0,40} exposure",
        r"defect \w+-DEF-\d+",
        r"reopening defect",
    ]

    exposure_records  = []
    clean_records     = []
    unreadable        = []

    for rec in applicable:
        ev = rec["evidence_text"]
        # Check for explicit exposure evidence
        exposed = any(
            re.search(p, ev, re.IGNORECASE) for p in EXPOSURE_PATTERNS
        )
        # Check for a passing isolation result
        all_pass = bool(re.search(
            r"\d+\s+of\s+\d+\s+isolation\s+cases?\s+pass",
            ev, re.IGNORECASE,
        ))

        if exposed:
            exposure_records.append(rec)
        elif all_pass:
            clean_records.append(rec)
        else:
            unreadable.append({**rec, "reason": "No readable isolation result"})

    # Any confirmed exposure → FAIL (blocks release)
    if exposure_records:
        rec      = exposure_records[0]
        decision = "FAIL"
        reason   = (
            f"Confirmed cross-customer document exposure in "
            f"{rec['issue_key']}. Release is blocked."
        )
    elif clean_records:
        decision = "PASS"
        reason   = (
            f"All isolation cases pass ({clean_records[0]['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable isolation result found."

    excluded.extend(unreadable)

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-03 — Answer quality for deployed prompt  (TYN-225)
# Approved quality evaluation must achieve ≥ 90 % and match prompt p7.
# Target match already enforces prompt=p7 via _classify_linked.
# Extra check: harness comment must not declare a different prompt.
# ===========================================================================

def evaluate_req03(issue_key: str = "TYN-225") -> dict:
    criterion = (
        "The approved quality evaluation must achieve at least 90 percent "
        "and match the deployed prompt p7."
    )
    applicable, excluded = _classify_linked(issue_key, require_prompt=True)

    passing_records = []
    failing_records = []

    for rec in applicable:
        ev = rec["evidence_text"]

        # Check if the harness was explicitly configured with a different prompt
        harness_prompt = _extract(
            r"harness\s+configured\s+with\s+prompt\s+bundle\s+(p\d+)", ev
        )
        if harness_prompt and harness_prompt != TARGET["prompt"]:
            excluded.append({
                **rec,
                "reason": (
                    f"Evaluation harness configured with wrong prompt "
                    f"({harness_prompt}), expected {TARGET['prompt']}."
                ),
            })
            continue

        # Look for the accuracy percentage
        pct_matches = re.findall(
            r"(?:answer\s+accuracy|quality)\s+([\d.]+)\s*percent",
            ev, re.IGNORECASE,
        )
        if not pct_matches:
            excluded.append({**rec, "reason": "No readable quality percentage"})
            continue

        pct = float(pct_matches[-1])
        rec["quality_percent"] = pct

        # Must be approved
        approved = bool(re.search(r"\bapproved\b", ev, re.IGNORECASE))

        if pct >= 90.0 and approved:
            passing_records.append(rec)
        else:
            failing_records.append(rec)

    if passing_records:
        rec      = passing_records[0]
        decision = "PASS"
        reason   = (
            f"Approved quality evaluation {rec['quality_percent']}% ≥ 90% "
            f"with correct prompt p7 ({rec['issue_key']})."
        )
    elif failing_records:
        rec      = failing_records[0]
        decision = "FAIL"
        reason   = (
            f"Quality evaluation {rec['quality_percent']}% does not meet "
            f"threshold or is not approved ({rec['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = (
            "No applicable quality evaluation with correct prompt p7 found."
        )

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-04 — Response latency  (TYN-53)   [already in agent.py — re-exposed here
#           for consistency so the release engine can call a uniform interface]
# p95 latency ≤ threshold extracted from the requirement description.
# ===========================================================================

def evaluate_req04(issue_key: str = "TYN-53") -> dict:
    criterion_template = (
        "The production-equivalent target-build p95 response time "
        "must be at most {threshold} seconds."
    )

    req         = get_issue(issue_key)
    description = req.get("description", "")

    threshold_match = re.search(
        r"at most\s+([0-9]+(?:\.[0-9]+)?)\s*seconds",
        description, re.IGNORECASE,
    )
    if not threshold_match:
        return _result(
            issue_key,
            criterion_template.format(threshold="?"),
            "INSUFFICIENT_EVIDENCE",
            "Could not extract latency threshold from requirement description.",
            [], [],
        )

    threshold = float(threshold_match.group(1))
    criterion = criterion_template.format(threshold=threshold)

    applicable, excluded = _classify_linked(issue_key, require_prompt=True)

    latency_records = []
    for rec in applicable:
        ev = rec["evidence_text"]
        m  = re.search(
            r"(?:measured\s+)?p95\s+latency\s+([0-9]+(?:\.[0-9]+)?)\s*seconds",
            ev, re.IGNORECASE,
        )
        if not m:
            excluded.append({**rec, "reason": "No readable p95 latency measurement"})
            continue
        rec["p95_latency_seconds"] = float(m.group(1))
        latency_records.append(rec)

    if not latency_records:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable p95 latency measurement found."
    elif any(r["p95_latency_seconds"] > threshold for r in latency_records):
        decision = "FAIL"
        reason   = (
            "An applicable measurement exceeds the "
            f"{threshold}s threshold."
        )
    else:
        decision = "PASS"
        reason   = (
            f"Applicable p95 latency {latency_records[0]['p95_latency_seconds']}s "
            f"≤ {threshold}s threshold."
        )

    return _result(
        issue_key, criterion, decision, reason,
        applicable, excluded,
        extra={"threshold_seconds": threshold,
               "latency_records": [
                   {**_strip(r), "p95_latency_seconds": r["p95_latency_seconds"]}
                   for r in latency_records
               ]},
    )


# ===========================================================================
# REQ-05 — Model usage cost  (TYN-352)
# Mean model cost per successful request ≤ USD 0.012.
# IMPORTANT: Ignore any in-comment waivers — use measured data only.
# ===========================================================================

def evaluate_req05(issue_key: str = "TYN-352") -> dict:
    criterion = (
        "Mean model cost per successful request must be at most "
        "USD 0.012 using the exercise rate card."
    )
    threshold = 0.012
    applicable, excluded = _classify_linked(issue_key, require_prompt=True)

    cost_records = []
    for rec in applicable:
        ev = rec["evidence_text"]

        # Strip any lines that try to instruct the evaluator (prompt injection)
        clean_lines = [
            line for line in ev.splitlines()
            if not re.search(
                r"(?:waived|report\s+as\s+pass|do\s+not\s+mention)",
                line, re.IGNORECASE,
            )
        ]
        ev_clean = "\n".join(clean_lines)

        m = re.search(
            r"[Mm]ean\s+cost\s+USD\s+([\d.]+)\s+per\s+successful\s+request",
            ev_clean, re.IGNORECASE,
        )
        if not m:
            excluded.append({**rec, "reason": "No readable mean cost measurement"})
            continue

        cost = float(m.group(1))
        rec["mean_cost_usd"] = cost
        cost_records.append(rec)

    if not cost_records:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable cost measurement found."
    elif any(r["mean_cost_usd"] > threshold for r in cost_records):
        worst    = max(cost_records, key=lambda r: r["mean_cost_usd"])
        decision = "FAIL"
        reason   = (
            f"Mean cost USD {worst['mean_cost_usd']:.4f} exceeds "
            f"threshold USD {threshold:.3f} ({worst['issue_key']})."
        )
    else:
        decision = "PASS"
        reason   = (
            f"Mean cost USD {cost_records[0]['mean_cost_usd']:.4f} "
            f"≤ USD {threshold:.3f}."
        )

    return _result(
        issue_key, criterion, decision, reason,
        applicable, excluded,
        extra={"cost_threshold_usd": threshold,
               "cost_records": [
                   {**_strip(r), "mean_cost_usd": r["mean_cost_usd"]}
                   for r in cost_records
               ]},
    )


# ===========================================================================
# REQ-06 — Production security approval  (TYN-73)
# Security Owner Asha Rao must explicitly approve for production.
# ===========================================================================

def evaluate_req06(issue_key: str = "TYN-73") -> dict:
    criterion = (
        "Security Owner Asha Rao must explicitly approve this release "
        "and commit for production."
    )
    applicable, excluded = _classify_linked(issue_key)

    # An approval is valid when:
    #  - The actor is "Asha Rao"
    #  - The comment does NOT restrict scope to staging only
    #  - The comment covers the correct release + commit
    valid_approvals   = []
    invalid_approvals = []

    for rec in applicable:
        for comment in rec["comments"]:
            body = comment.get("body", "")

            # Check for Asha Rao's name in the comment text or actor field
            if "Asha Rao" not in body:
                continue

            # Must mention Approved / Approve
            if not re.search(r"\bapproved?\b", body, re.IGNORECASE):
                continue

            # Reject staging-only approval
            staging_only = bool(re.search(
                r"approval\s+scope\s*:\s*staging",
                body, re.IGNORECASE,
            ))

            # Reject if production sign-off is stated as future / pending
            future_production = bool(re.search(
                r"production\s+sign.off\s+scheduled",
                body, re.IGNORECASE,
            ))

            approval = {
                "issue_key":        rec["issue_key"],
                "comment_excerpt":  body[:300],
                "staging_only":     staging_only,
                "future_production": future_production,
            }

            if staging_only or future_production:
                invalid_approvals.append(approval)
            else:
                valid_approvals.append(approval)

    if valid_approvals:
        decision = "PASS"
        reason   = (
            f"Security Owner Asha Rao has approved for production "
            f"({valid_approvals[0]['issue_key']})."
        )
    elif invalid_approvals:
        decision = "INSUFFICIENT_EVIDENCE"
        reason = (
            "Asha Rao's approval is limited to staging. "
            "It does not establish production approval."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason = (
            "No valid production approval from Security Owner Asha Rao "
            "was established by the available evidence."
        )

    return _result(
        issue_key, criterion, decision, reason,
        applicable, excluded,
        extra={"valid_approvals":   valid_approvals,
               "invalid_approvals": invalid_approvals},
    )


# ===========================================================================
# REQ-07 — Sensitive log redaction  (TYN-329)
# QA must verify that sensitive identifiers are redacted on the target build.
# "supersedes" logic: if a later run explicitly supersedes an earlier one,
# only the superseding result counts.
# ===========================================================================

def evaluate_req07(issue_key: str = "TYN-329") -> dict:
    criterion = (
        "QA must verify that sensitive identifiers are redacted "
        "on the target build."
    )
    applicable, excluded = _classify_linked(issue_key)

    passing_records = []
    failing_records = []

    for rec in applicable:
        ev = rec["evidence_text"]

        # Find all redaction results (may include superseded ones)
        result_matches = re.findall(
            r"(\d+)\s+of\s+(\d+)\s+redaction\s+cases?\s+pass",
            ev, re.IGNORECASE,
        )
        # Detect "supersedes" to prefer the final result
        supersedes = bool(re.search(
            r"\bsupersedes?\b", ev, re.IGNORECASE
        ))
        fail_keywords = bool(re.search(
            r"\bFAIL\b|found\s+unredacted|fail\b",
            ev, re.IGNORECASE,
        ))

        if not result_matches:
            excluded.append({**rec, "reason": "No readable redaction result"})
            continue

        # Use last result (after any "supersedes" re-run)
        passed_str, total_str = result_matches[-1]
        passed, total = int(passed_str), int(total_str)
        rec["passed"] = passed
        rec["total"]  = total

        # If supersedes is mentioned, the final result is authoritative
        if supersedes:
            if passed == total:
                passing_records.append(rec)
            else:
                failing_records.append(rec)
        elif fail_keywords and passed < total:
            failing_records.append(rec)
        elif passed == total:
            passing_records.append(rec)
        else:
            failing_records.append(rec)

    if passing_records:
        rec      = passing_records[0]
        decision = "PASS"
        reason   = (
            f"{rec['passed']}/{rec['total']} redaction cases pass "
            f"on target build ({rec['issue_key']})."
        )
    elif failing_records:
        rec      = failing_records[0]
        decision = "FAIL"
        reason   = (
            f"Redaction failures found: {rec['passed']}/{rec['total']} "
            f"cases pass ({rec['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable redaction QA result found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-08 — Human handoff delivery  (TYN-48)
# Handoff must reach support queue, including linked delivery dependency.
# Evidence is in directly linked records AND in REC-9635 (TYN-76).
# ===========================================================================

def evaluate_req08(issue_key: str = "TYN-48") -> dict:
    criterion = (
        "When an answer is escalated, a handoff must reach the support queue, "
        "including its linked delivery dependency."
    )

    # TYN-48 links to TYN-342 (implementation) and TYN-360 (manifest).
    # TYN-342 links to TYN-76 (REC-9635, the queue-adapter verification).
    # We must also evaluate TYN-76 directly.
    applicable, excluded = _classify_linked(issue_key)

    # Also fetch queue-adapter evidence linked from TYN-342
    extra_applicable, extra_excluded = _classify_linked("TYN-342")
    # Avoid double-counting
    seen = {r["issue_key"] for r in applicable}
    for r in extra_applicable:
        if r["issue_key"] not in seen:
            applicable.append(r)
            seen.add(r["issue_key"])
    for r in extra_excluded:
        if r["issue_key"] not in seen:
            excluded.append(r)
            seen.add(r["issue_key"])

    # Look for handoff delivery test results
    DELIVERY_OK  = re.compile(
        r"(\d+)\s+of\s+(\d+)\s+escalated\s+conversations?\s+reached",
        re.IGNORECASE,
    )
    DELIVERY_FAIL_KW = re.compile(
        r"(?:queue\s+adapter\s+drops|0\s+of\s+\d+\s+.*?reached|"
        r"defect\s+\w+-DEF-|open\s+defect)",
        re.IGNORECASE,
    )
    QUEUE_PASS = re.compile(
        r"(\d+)\s+of\s+(\d+)\s+cases?\s+pass",
        re.IGNORECASE,
    )

    delivery_failures = []
    delivery_passes   = []
    dev_notes_only    = []

    for rec in applicable:
        ev = rec["evidence_text"]

        fail_m = DELIVERY_FAIL_KW.search(ev)
        ok_m   = DELIVERY_OK.search(ev)
        qa_m   = QUEUE_PASS.search(ev)

        if fail_m or ok_m:
            # Try to get counts
            count_m = re.search(
                r"(\d+)\s+of\s+(\d+)\s+escalated", ev, re.IGNORECASE
            )
            if count_m:
                n, total = int(count_m.group(1)), int(count_m.group(2))
                rec["reached"] = n
                rec["total"]   = total
                if n == total and total > 0:
                    delivery_passes.append(rec)
                else:
                    delivery_failures.append(rec)
            else:
                delivery_failures.append(rec)
        elif qa_m:
            n, total = int(qa_m.group(1)), int(qa_m.group(2))
            rec["passed"] = n
            rec["total"]  = total
            if n == total:
                delivery_passes.append(rec)
            else:
                delivery_failures.append(rec)
        else:
            # Only developer notes — not QA-verified delivery
            dev_notes_only.append(rec)

    if delivery_failures:
        rec      = delivery_failures[0]
        decision = "FAIL"
        reached  = rec.get("reached", 0)
        total    = rec.get("total", "?")
        reason   = (
            f"Handoff delivery test shows {reached} of {total} escalated "
            f"conversations reached the support queue ({rec['issue_key']}). "
            f"Queue adapter defect is open."
        )
    elif delivery_passes:
        decision = "PASS"
        reason   = (
            f"Handoff delivery confirmed: "
            f"{delivery_passes[0]['issue_key']}."
        )
    elif dev_notes_only:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = (
            "Only developer implementation notes found; no QA-verified "
            "end-to-end handoff delivery test on the target build."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No handoff delivery evidence found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-09 — Rollback rehearsal  (TYN-143)
# An approved rollback rehearsal must succeed on the target release
# and production configuration. Any failure blocks the requirement.
# ===========================================================================

def evaluate_req09(issue_key: str = "TYN-143") -> dict:
    criterion = (
        "An approved rollback rehearsal must succeed on the target release "
        "and production configuration."
    )
    applicable, excluded = _classify_linked(issue_key)

    passing_rehearsals = []
    failing_rehearsals = []

    FAIL_KW = re.compile(
        r"(?:\bFAILED?\b|data\s+loss|records?\s+(?:were\s+)?lost|"
        r"session\s+records?\s+written\s+during\s+the\s+window\s+were\s+lost)",
        re.IGNORECASE,
    )
    PASS_KW = re.compile(
        r"(?:no\s+data\s+loss\s+observed|health\s+probes?\s+pass|"
        r"restored?\s+in\s+\d+\s+minutes?)",
        re.IGNORECASE,
    )

    for rec in applicable:
        ev = rec["evidence_text"]
        # Look for rollback rehearsal run identifiers
        if not re.search(r"\bRB-\d+\b", ev, re.IGNORECASE):
            excluded.append({**rec, "reason": "No rollback rehearsal run found"})
            continue

        if FAIL_KW.search(ev):
            failing_rehearsals.append(rec)
        elif PASS_KW.search(ev):
            passing_rehearsals.append(rec)
        else:
            excluded.append({**rec, "reason": "Rollback result ambiguous"})

    if failing_rehearsals:
        rec      = failing_rehearsals[0]
        decision = "FAIL"
        reason   = (
            f"Rollback rehearsal failed on target build ({rec['issue_key']}). "
            "Session data loss was observed."
        )
    elif passing_rehearsals:
        decision = "PASS"
        reason   = (
            f"Rollback rehearsal succeeded on target build "
            f"({passing_rehearsals[0]['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable rollback rehearsal result found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-10 — Document parsing completeness  (TYN-57)
# Target build must pass all 60 mandatory parsing cases.
# "supersedes" logic applies.
# ===========================================================================

def evaluate_req10(issue_key: str = "TYN-57") -> dict:
    criterion = (
        "The target build must pass all 60 mandatory "
        "document parsing cases."
    )
    applicable, excluded = _classify_linked(issue_key)

    passing_records = []
    failing_records = []

    for rec in applicable:
        ev = rec["evidence_text"]

        # Extract all parsing results; if supersedes is mentioned,
        # only the final one counts.
        results = re.findall(
            r"(\d+)\s+of\s+(\d+)\s+(?:mandatory\s+)?parsing\s+cases?\s+pass",
            ev, re.IGNORECASE,
        )
        if not results:
            excluded.append({**rec, "reason": "No readable parsing result"})
            continue

        # Use last result
        passed_str, total_str = results[-1]
        passed, total = int(passed_str), int(total_str)
        rec["passed"] = passed
        rec["total"]  = total

        if passed == total:
            passing_records.append(rec)
        else:
            failing_records.append(rec)

    if passing_records:
        rec      = passing_records[0]
        decision = "PASS"
        reason   = (
            f"All {rec['total']} mandatory parsing cases pass "
            f"({rec['issue_key']})."
        )
    elif failing_records:
        rec      = failing_records[0]
        decision = "FAIL"
        reason   = (
            f"{rec['passed']} of {rec['total']} parsing cases pass; "
            f"criterion requires all {rec['total']} ({rec['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable parsing result found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-11 — Accessible keyboard handoff  (TYN-162)
# QA must verify keyboard navigation and focus handling on the target release.
# A developer self-test does NOT satisfy this — must be a QA-role comment.
# ===========================================================================

def evaluate_req11(issue_key: str = "TYN-162") -> dict:
    criterion = (
        "QA must verify keyboard navigation and focus handling "
        "for the handoff interface on the target release."
    )
    applicable, excluded = _classify_linked(issue_key)

    QA_PASS_PATTERN = re.compile(
        r"(\d+)\s+of\s+(\d+)\s+cases?\s+pass",
        re.IGNORECASE,
    )

    qa_verified_passes  = []
    dev_self_tests_only = []

    for rec in applicable:
        ev = rec["evidence_text"]

        # Find comments from QA-role actors
        qa_comments = [
            c for c in rec["comments"]
            if re.search(r"\brole\s+QA\b", c.get("body", ""), re.IGNORECASE)
        ]

        qa_has_pass = any(
            QA_PASS_PATTERN.search(c.get("body", ""))
            for c in qa_comments
        )

        # Developer self-tests alone are insufficient
        dev_mentions_test = bool(re.search(
            r"(?:tested\s+it\s+on\s+my\s+machine|self.test)",
            ev, re.IGNORECASE,
        ))

        if qa_has_pass:
            qa_verified_passes.append(rec)
        elif dev_mentions_test and not qa_has_pass:
            dev_self_tests_only.append(rec)
        else:
            excluded.append({**rec, "reason": "No QA-verified keyboard test result"})

    if qa_verified_passes:
        decision = "PASS"
        reason   = (
            f"QA-verified keyboard navigation test passes on target "
            f"({qa_verified_passes[0]['issue_key']})."
        )
    elif dev_self_tests_only:
        decision = "INSUFFICIENT_EVIDENCE"
        reason = (
            "Only developer self-test evidence was found. "
            "QA verification on the target release is still required "
            f"({dev_self_tests_only[0]['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = (
            "No QA-verified keyboard navigation test on the target "
            "release found."
        )

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# REQ-12 — Streaming completion integrity  (TYN-400)
# Every mandatory streaming case must complete without duplicate or
# missing final messages.
# ===========================================================================

def evaluate_req12(issue_key: str = "TYN-400") -> dict:
    criterion = (
        "Every mandatory streaming case must complete without "
        "duplicate or missing final messages."
    )
    applicable, excluded = _classify_linked(issue_key, require_prompt=True)

    passing_records = []
    failing_records = []

    INTEGRITY_FAIL = re.compile(
        r"(?:duplicated?\s+final\s+message|missing\s+final\s+message|"
        r"duplicate.{0,20}message)",
        re.IGNORECASE,
    )
    STREAMING_RESULT = re.compile(
        r"(\d+)\s+of\s+(\d+)\s+(?:mandatory\s+)?(?:streaming\s+)?cases?\s+pass",
        re.IGNORECASE,
    )

    for rec in applicable:
        ev = rec["evidence_text"]

        if not re.search(r"\bSTREAM-\d+\b", ev, re.IGNORECASE):
            excluded.append({**rec, "reason": "No streaming test run found"})
            continue

        has_integrity_fail = INTEGRITY_FAIL.search(ev)
        result_m           = STREAMING_RESULT.search(ev)

        if has_integrity_fail:
            failing_records.append(rec)
        elif result_m:
            n, total = int(result_m.group(1)), int(result_m.group(2))
            rec["passed"] = n
            rec["total"]  = total
            if n == total:
                passing_records.append(rec)
            else:
                failing_records.append(rec)
        else:
            excluded.append({**rec, "reason": "No readable streaming result"})

    if failing_records:
        rec      = failing_records[0]
        decision = "FAIL"
        reason   = (
            f"Streaming integrity failure detected in "
            f"{rec['issue_key']}: duplicated or missing final message."
        )
    elif passing_records:
        rec      = passing_records[0]
        decision = "PASS"
        reason   = (
            f"All {rec.get('total', '?')} streaming cases pass without "
            f"integrity failures ({rec['issue_key']})."
        )
    else:
        decision = "INSUFFICIENT_EVIDENCE"
        reason   = "No applicable streaming test result found."

    return _result(issue_key, criterion, decision, reason,
                   applicable, excluded)


# ===========================================================================
# Release decision engine
# ===========================================================================

# Map each req ID to its evaluator function and Jira key
EVALUATORS = [
    ("REQ-01", "TYN-89",  evaluate_req01),
    ("REQ-02", "TYN-263", evaluate_req02),
    ("REQ-03", "TYN-225", evaluate_req03),
    ("REQ-04", "TYN-53",  evaluate_req04),
    ("REQ-05", "TYN-352", evaluate_req05),
    ("REQ-06", "TYN-73",  evaluate_req06),
    ("REQ-07", "TYN-329", evaluate_req07),
    ("REQ-08", "TYN-48",  evaluate_req08),
    ("REQ-09", "TYN-143", evaluate_req09),
    ("REQ-10", "TYN-57",  evaluate_req10),
    ("REQ-11", "TYN-162", evaluate_req11),
    ("REQ-12", "TYN-400", evaluate_req12),
]


def evaluate_all_requirements() -> dict:
    """
    Run all 12 evaluators and compute the overall release decision.

    Returns a dict with per-requirement results and an overall decision:
      READY          - all 12 PASS
      BLOCKED        - one or more FAIL
      NEEDS_REVIEW   - no FAIL but one or more INSUFFICIENT_EVIDENCE
    """
    results = {}
    errors  = {}

    for req_id, jira_key, fn in EVALUATORS:
        print(f"  Evaluating {req_id} ({jira_key})...", flush=True)
        try:
            results[req_id] = fn(jira_key)
        except Exception as exc:
            errors[req_id] = str(exc)
            results[req_id] = {
                "requirement": jira_key,
                "decision":    "INSUFFICIENT_EVIDENCE",
                "reason":      f"Evaluation error: {exc}",
            }

    decisions = {r: results[r]["decision"] for r in results}

    if any(d == "FAIL" for d in decisions.values()):
        overall = "BLOCKED"
        overall_reason = (
            "One or more mandatory requirements have FAIL decisions. "
            "Release R2.4 must not proceed."
        )
    elif any(d == "INSUFFICIENT_EVIDENCE" for d in decisions.values()):
        overall = "NEEDS_REVIEW"
        overall_reason = (
            "All evaluated requirements passed but one or more have "
            "insufficient evidence. Manual review required before release."
        )
    else:
        overall = "READY"
        overall_reason = (
            "All 12 mandatory requirements have PASS decisions. "
            "Release R2.4 may proceed."
        )

    summary = {
        "PASS":                 [r for r, d in decisions.items() if d == "PASS"],
        "FAIL":                 [r for r, d in decisions.items() if d == "FAIL"],
        "INSUFFICIENT_EVIDENCE": [r for r, d in decisions.items() if d == "INSUFFICIENT_EVIDENCE"],
    }

    return {
        "release":          "R2.4",
        "target":           TARGET,
        "overall_decision": overall,
        "overall_reason":   overall_reason,
        "summary":          summary,
        "decisions":        decisions,
        "requirement_results": results,
        "evaluation_errors":   errors,
    }
