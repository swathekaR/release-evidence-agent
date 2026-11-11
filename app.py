"""
Release Evidence Agent — Interactive Investigation UI (Streamlit)
Yellow Networks Release Assessment R2.4

Run with:
    cd c:\\YellowNetworksAssessment\\ReleaseAgent
    .\\venv\\Scripts\\streamlit.exe run app.py
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from agent import run_requirement_investigation, _build_full_report

import streamlit as st

# Ensure local imports resolve
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Jira_tools import get_issue, get_issue_comments, get_linked_issues
from evaluators import EVALUATORS, TARGET, evaluate_all_requirements
from agent import run_requirement_investigation

# Page configuration
st.set_page_config(
    page_title="Jira Release Evidence Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #0052cc;
        margin-bottom: 12px;
    }
    .badge-pass {
        background-color: #e3fcef;
        color: #006644;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 700;
        display: inline-block;
    }
    .badge-fail {
        background-color: #ffebe6;
        color: #bf2600;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 700;
        display: inline-block;
    }
    .badge-review {
        background-color: #fff0b3;
        color: #172b4d;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 700;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Requirement Catalog Metadata
# ---------------------------------------------------------------------------
REQ_METADATA = {
    "REQ-01": {"jira": "TYN-89",  "name": "Automated regression tests", "desc": "All automated regression cases must pass on target build."},
    "REQ-02": {"jira": "TYN-263", "name": "Customer document isolation", "desc": "Every isolation case must pass; any cross-customer exposure blocks release."},
    "REQ-03": {"jira": "TYN-225", "name": "Answer quality for deployed prompt", "desc": "Quality evaluation must achieve ≥ 90% and match prompt p7."},
    "REQ-04": {"jira": "TYN-53",  "name": "Response latency", "desc": "Production-equivalent target-build p95 response time must be ≤ 2.0s."},
    "REQ-05": {"jira": "TYN-352", "name": "Model usage cost", "desc": "Mean model cost per request must be ≤ USD 0.012 (waivers rejected)."},
    "REQ-06": {"jira": "TYN-73",  "name": "Production security approval", "desc": "Security Owner Asha Rao must explicitly approve for production."},
    "REQ-07": {"jira": "TYN-329", "name": "Sensitive log redaction", "desc": "QA must verify sensitive identifiers are redacted on target build."},
    "REQ-08": {"jira": "TYN-48",  "name": "Human handoff delivery", "desc": "Escalated handoffs must reach support queue via queue-adapter."},
    "REQ-09": {"jira": "TYN-143", "name": "Rollback rehearsal", "desc": "Approved rollback rehearsal must succeed on target without data loss."},
    "REQ-10": {"jira": "TYN-57",  "name": "Document parsing completeness", "desc": "Target build must pass all 60 mandatory document parsing cases."},
    "REQ-11": {"jira": "TYN-162", "name": "Accessible keyboard handoff", "desc": "QA must verify keyboard navigation and focus handling on target."},
    "REQ-12": {"jira": "TYN-400", "name": "Streaming completion integrity", "desc": "Every mandatory streaming case must complete without duplicate/missing messages."},
}

# ---------------------------------------------------------------------------
# Sidebar: Target Configuration & System Status
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🛡️ Release Evidence Agent")
    st.caption("Deterministic Release Gate System")
    st.divider()

    st.subheader("🎯 Target Release")
    st.markdown(f"""
    - **Release:** `{TARGET['release']}`
    - **Commit:** `{TARGET['commit']}`
    - **Service:** `{TARGET['service']}`
    - **Environment:** `{TARGET['environment']}`
    - **Prompt:** `{TARGET['prompt']}`
    """)
    st.divider()

    st.subheader("ℹ️ System Architecture")
    st.markdown("""
    - **Source of Truth:** Jira Cloud (`TYN`)
    - **Dataset:** `tyn-release-assessment-v2`
    - **Rules:** Jira workflow status is **never** proof of compliance.
    - **Evaluators:** 12 Python deterministic gate evaluators.
    """)

# ---------------------------------------------------------------------------
# Main Tabs: Single Requirement Investigation vs Full Assessment
# ---------------------------------------------------------------------------
tab1, tab2 = st.tabs(["🔍 Requirement Investigation", "📊 Full Release Assessment"])

# ===========================================================================
# TAB 1: Requirement Investigation
# ===========================================================================
with tab1:
    st.header("Requirement Evidence Investigation")
    st.markdown("Select a requirement to investigate linked Jira issues, commit metadata, and evaluate compliance.")

    col1, col2 = st.columns([1, 2])

    with col1:
        req_options = [
            f"{req_id} — {meta['name']} ({meta['jira']})"
            for req_id, meta in REQ_METADATA.items()
        ]
        selected_option = st.selectbox("Select a requirement", req_options, index=1)
        selected_req_id = selected_option.split(" — ")[0]
        selected_jira_key = REQ_METADATA[selected_req_id]["jira"]

    with col2:
        default_question = f"Inspect {selected_req_id} ({selected_jira_key}) and linked evidence records. Validate against release {TARGET['release']}, commit {TARGET['commit']}, and explain applicable vs excluded evidence."
        user_question = st.text_area("Investigation Prompt", value=default_question, height=85)

    investigate_btn = st.button("🚀 Investigate Requirement", type="primary", use_container_width=True)
    # Initialize LLM result variables for every Streamlit rerun
    llm_result = None
    llm_error = None

    if investigate_btn:
        st.divider()
        progress_bar = st.progress(0, text="Connecting to Jira Cloud...")

        start_time = time.time()
        meta = REQ_METADATA[selected_req_id]

        # Step 1: Fetch requirement
        progress_bar.progress(25, text=f"Retrieving {selected_jira_key} details...")
        req_issue = get_issue(selected_jira_key)

        # Step 2: Fetch links
        progress_bar.progress(50, text=f"Inspecting linked evidence records...")
        linked_keys = get_linked_issues(selected_jira_key)
        # Step 3: Run evaluator function
        progress_bar.progress(70, text=f"Running deterministic evaluator for {selected_req_id}...")
        evaluator_fn = next((fn for rid, jkey, fn in EVALUATORS if rid == selected_req_id), None)

        if evaluator_fn:
            eval_result = evaluator_fn(selected_jira_key)
        else:
            eval_result = {"decision": "INSUFFICIENT_EVIDENCE", "reason": "No evaluator found"}

        # Step 4: Run LLM agent investigation on verified evidence
        progress_bar.progress(85, text="LLM agent analyzing verified Jira evidence...")
        llm_result = None
        llm_error = None

        try:
            llm_result = run_requirement_investigation(
                selected_jira_key,
                user_question,
                eval_result
            )
        except Exception as error:
            llm_error = str(error)

        progress_bar.progress(100, text="Investigation completed!")
        time.sleep(0.3)
        progress_bar.empty()

        elapsed = round(time.time() - start_time, 2)

        # --- Decision Banner ---
        decision = eval_result.get("decision", "INSUFFICIENT_EVIDENCE")
        if decision == "PASS":
            st.success(f"### Decision: ✅ PASS\n**Reason:** {eval_result.get('reason')}")
        elif decision == "FAIL":
            st.error(f"### Decision: ❌ FAIL\n**Reason:** {eval_result.get('reason')}")
        else:
            st.warning(f"### Decision: ⚠️ INSUFFICIENT EVIDENCE\n**Reason:** {eval_result.get('reason')}")

        st.caption(f"⏱️ Investigation completed in {elapsed}s | Target: {TARGET['release']} @ {TARGET['commit']}")

        # --- LLM Investigation Findings ---
        st.subheader("🤖 AI Investigation Findings")

        if llm_result:
            st.success(
                f"LLM investigation completed in "
                f"{llm_result['execution_time_seconds']} seconds ({llm_result.get('model', 'qwen2.5:3b')})"
            )
            st.markdown(llm_result["investigation_summary"])
        elif llm_error:
            st.warning(f"LLM investigation unavailable: {llm_error}")

        # --- Requirement Metadata ---
        with st.expander(f"📋 Requirement Details — {selected_jira_key}: {meta['name']}", expanded=True):
            st.markdown(f"**Acceptance Criterion:** {eval_result.get('criterion', meta['desc'])}")
            st.markdown(f"**Jira Issue Summary:** {req_issue.get('summary', 'N/A')}")
            st.markdown(f"**Jira Status:** `{req_issue.get('status', 'N/A')}` *(Note: Jira workflow status is not used as evidence)*")
            st.markdown(f"**Linked Issues Discovered ({len(linked_keys)}):** {', '.join(linked_keys) or 'None'}")

        # --- Evidence Breakdown ---
        col_app, col_exc = st.columns(2)

        with col_app:
            applicable = eval_result.get("applicable_evidence", [])
            st.subheader(f"✅ Applicable Evidence ({len(applicable)})")
            if not applicable:
                st.info("No applicable evidence matching target release configuration found.")
            for item in applicable:
                with st.container(border=True):
                    st.markdown(f"**Issue:** `{item.get('issue_key')}`")
                    st.markdown(f"**Summary:** {item.get('summary', 'N/A')}")
                    st.markdown(f"- **Release:** `{item.get('release')}` | **Commit:** `{item.get('commit')}`")
                    st.markdown(f"- **Service:** `{item.get('service')}` | **Environment:** `{item.get('environment')}`")
                    if item.get("prompt"):
                        st.markdown(f"- **Prompt:** `{item.get('prompt')}`")
                    if item.get("p95_latency_seconds") is not None:
                        st.markdown(f"- **Measured p95 Latency:** `{item.get('p95_latency_seconds')}s`")
                    if item.get("mean_cost_usd") is not None:
                        st.markdown(f"- **Measured Mean Cost:** `USD {item.get('mean_cost_usd'):.4f}`")
                    st.markdown("**Target Match:** `YES`")

        with col_exc:
            excluded = eval_result.get("excluded_evidence", [])
            st.subheader(f"🚫 Excluded Records ({len(excluded)})")
            if not excluded:
                st.info("No records were excluded.")
            for item in excluded:
                with st.container(border=True):
                    st.markdown(f"**Issue:** `{item.get('issue_key')}`")
                    if item.get("summary"):
                        st.markdown(f"**Summary:** {item.get('summary')}")
                    st.markdown(f"**Exclusion Reason:** `{item.get('reason', 'Excluded')}`")
                    mismatches = item.get("mismatched_fields", [])
                    if mismatches:
                        st.markdown("**Mismatched Fields:**")
                        for m in mismatches:
                            st.markdown(f"- `{m['field']}`: actual=`{m['actual']}`, expected=`{m['expected']}`")

        # --- Trace & Raw JSON ---
        with st.expander("🛠️ Execution Trace & JSON Output"):
            st.json(eval_result)

# ===========================================================================
# TAB 2: Full Release Assessment
# ===========================================================================
with tab2:
    st.header("Release R2.4 Gate Assessment")
    st.markdown("Evaluate all 12 mandatory requirements against release candidate **R2.4**.")

    run_all_btn = st.button("⚡ Run Full 12-Requirement Release Gate", type="primary")

    if run_all_btn:
        with st.spinner("Executing full 12-requirement deterministic evaluation across Jira Cloud..."):
            t_start = time.time()
            release_result = evaluate_all_requirements()
            t_elapsed = round(time.time() - t_start, 2)

        overall = release_result.get("overall_decision", "BLOCKED")
        reason = release_result.get("overall_reason", "")

        # Summary KPIs
        decisions = release_result.get("decisions", {})
        pass_count = sum(1 for d in decisions.values() if d == "PASS")
        fail_count = sum(1 for d in decisions.values() if d == "FAIL")
        review_count = sum(1 for d in decisions.values() if d == "INSUFFICIENT_EVIDENCE")

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Overall Gate", overall, delta="BLOCKED" if overall == "BLOCKED" else "READY")
        kpi2.metric("Passed Requirements", f"{pass_count} / 12")
        kpi3.metric("Failed Requirements", f"{fail_count} / 12")
        kpi4.metric("Needs Review", f"{review_count} / 12")

        if overall == "BLOCKED":
            st.error(f"### ❌ RELEASE GATE: BLOCKED\n{reason}")
        elif overall == "READY":
            st.success(f"### ✅ RELEASE GATE: READY\n{reason}")
        else:
            st.warning(f"### ⚠️ RELEASE GATE: NEEDS REVIEW\n{reason}")

        st.caption(f"Evaluated all 12 requirements in {t_elapsed}s.")

        # Summary Table
        st.subheader("Requirement Decision Matrix")
        rows = []
        for req_id, jira_key, _ in EVALUATORS:
            d = decisions.get(req_id, "UNKNOWN")
            res = release_result.get("requirement_results", {}).get(req_id, {})
            rows.append({
                "Requirement": req_id,
                "Jira Issue": jira_key,
                "Name": REQ_METADATA.get(req_id, {}).get("name", ""),
                "Decision": "✅ PASS" if d == "PASS" else ("❌ FAIL" if d == "FAIL" else "⚠️ INSUFFICIENT"),
                "Finding": res.get("reason", "")
            })
        st.dataframe(rows, use_container_width=True)

        # Download Report Buttons
        
# Download Report Buttons

        # Download and save assessment reports
        st.divider()
        st.subheader("💾 Export Assessment Reports")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Generate report content
        txt_report = _build_full_report(release_result, t_elapsed)
        json_report_str = json.dumps(
            release_result,
            indent=2,
            ensure_ascii=False
        )

        # Save both reports in the project reports folder
        reports_folder = Path(__file__).resolve().parent / "reports"
        reports_folder.mkdir(parents=True, exist_ok=True)

        txt_path = reports_folder / f"release_R2.4_{timestamp}.txt"
        json_path = reports_folder / f"release_R2.4_{timestamp}.json"

        txt_path.write_text(txt_report, encoding="utf-8")
        json_path.write_text(json_report_str, encoding="utf-8")

        st.success("Both assessment reports have been saved successfully.")

        # JSON download
        st.download_button(
            label="📥 Download Release Assessment Report (JSON)",
            data=json_report_str,
            file_name=f"release_R2.4_assessment_{timestamp}.json",
            mime="application/json"
        )

        # TXT download
        st.download_button(
            label="📥 Download Release Assessment Report (TXT)",
            data=txt_report,
            file_name=f"release_R2.4_assessment_{timestamp}.txt",
            mime="text/plain"
        )

    
