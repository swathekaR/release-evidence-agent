
# Autonomous Jira Release Evidence Agent — R2.4 Assessment

A Jira-based release evidence assessment system that evaluates release readiness against 12 mandatory requirements using traceable evidence retrieval and deterministic Python evaluation.

---

## 1. Project Overview

In enterprise software deployment environments, release decisions must be supported by verifiable evidence rather than Jira workflow statuses such as `Done` or `In Progress`.

The objective of this project is to assess release candidate **R2.4** of the `atlas-assistant` service against 12 mandatory release requirements stored in Jira Cloud.

The system retrieves requirement records and their linked evidence, examines issue descriptions and comments, validates evidence against the target release configuration, and applies deterministic evaluation rules to produce a release readiness decision.

The possible overall decisions are:

- **READY** — All mandatory requirements pass.
- **BLOCKED** — At least one mandatory requirement fails.
- **NEEDS_REVIEW** — No requirement fails, but one or more lack sufficient evidence.

### Target Release Configuration

| Parameter | Target Value |
|---|---|
| Release | `R2.4` |
| Commit | `b7a91f2` |
| Service | `atlas-assistant` |
| Environment | `production` |
| Prompt | `p7` |

The prompt version is required only for criteria that depend on the deployed prompt configuration.

---

## 2. System Architecture

The implementation separates Jira evidence retrieval from release policy evaluation. This ensures that release decisions are produced by explicit, reproducible rules rather than relying on an LLM to make final compliance decisions.

### Architecture Flow

```text
                 Release Assessment
                         |
                         v
               Jira Requirements Search
                         |
                         v
              Requirement Issue Retrieval
                         |
                         v
              Linked Evidence Investigation
                         |
             +-----------+-----------+
             |                       |
             v                       v
        Issue Details           Issue Comments
             |                       |
             +-----------+-----------+
                         |
                         v
              Evidence Classification
                         |
                         v
              Target Configuration
                   Validation
                         |
                         v
             12 Deterministic Evaluators
                         |
                         v
               Requirement Decisions
                         |
             +-----------+-----------+
             |                       |
             v                       v
       Investigation Trace     Overall Decision
             |                       |
             +-----------+-----------+
                         |
                         v
                  Report Generator
                         |
              +----------+----------+
              |                     |
              v                     v
           TXT Report           JSON Report
```

### Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Issue Tracking / Evidence Source | Jira Cloud REST API |
| Agent Framework | LangGraph |
| LLM Integration | LangChain Ollama |
| Local LLM Configuration | Qwen 2.5:3B |
| Environment Configuration | python-dotenv |
| HTTP Communication | Requests |
| Output Formats | JSON and TXT |

### Main Source Files

| File | Responsibility |
|---|---|
| `agent.py` | Assessment execution, Jira tool definitions, orchestration, trace generation, and report generation |
| `app.py` | Streamlit interactive investigation UI for per-requirement and release gate evaluation |
| `Jira_tools.py` | Jira API authentication, issue retrieval, comment retrieval, and linked issue traversal |
| `evaluators.py` | Deterministic evaluation logic for all 12 requirements |
| `complete_jira_import.py` | Imports assessment comments and issue relationships into Jira |
| `requirements-agent.txt` | Pinned Python dependencies |
| `source_issue_mapping.json` | Source dataset to Jira issue mapping |
| `jira_import_audit.json` | Jira import execution audit |

**Important implementation detail:** The LangGraph ReAct agent and Ollama model are initialized in the application, and Jira investigation tools are defined. However, the current final assessment execution uses deterministic Python evaluators directly. The LLM agent is not invoked to generate the final decisions.

---

## 3. Jira Evidence Retrieval and Investigation

Jira Cloud is the source of truth for the assessment evidence.

The application retrieves requirement records and investigates their linked evidence through Jira REST API operations.

### Evidence Retrieval

The Jira integration supports:

- Searching requirement issues using JQL.
- Retrieving individual issue details.
- Retrieving paginated Jira comments.
- Traversing inward and outward issue relationships.
- Identifying linked evidence records.
- Extracting relevant evidence text for evaluation.

### Evidence Analysis

The evaluation process considers:

1. Requirement-to-evidence relationships.
2. Release, commit, service, and environment metadata.
3. Prompt version when relevant to a requirement.
4. Evidence contained in issue descriptions and comments.
5. QA verification and security approval roles.
6. Test results, quantitative thresholds, and confirmed defects.
7. Explicitly superseding retests where applicable.

### Evidence Provenance

Evidence must match the target configuration for the relevant criterion.

The application does not automatically treat missing metadata as a failure. It distinguishes between:

- Evidence that demonstrates compliance.
- Evidence that demonstrates a violation.
- Evidence that is missing, inapplicable, or inconclusive.

Jira issue status alone is never considered proof of compliance.

---

## 4. Deterministic Evaluation and Decision Rules

The project implements 12 requirement-specific evaluators in `evaluators.py`.

Each evaluator examines applicable evidence and produces one of three decisions.

### Requirement-Level Decisions

| Decision | Meaning |
|---|---|
| `PASS` | Applicable evidence establishes that the requirement is satisfied. |
| `FAIL` | Applicable evidence establishes a violation, confirmed defect, failed test, or unmet acceptance threshold. |
| `INSUFFICIENT_EVIDENCE` | Evidence is missing, inapplicable, or inconclusive, so compliance cannot be established. |

### Important Evaluation Rules

- Target release metadata is validated before evidence is considered applicable.
- Prompt version is checked only when required by the criterion.
- Jira workflow status is not treated as compliance evidence.
- An earlier failed test can be superseded by a later explicitly superseding successful retest.
- A confirmed target-build defect remains relevant unless valid evidence establishes its resolution.
- Staging approval does not establish production security approval.
- Developer-only testing does not replace mandatory QA verification.
- Untrusted or adversarial instructions inside Jira comments cannot override evaluation rules.
- Missing evidence is not automatically classified as a demonstrated failure.

### Overall Release Decision

The overall decision follows this hierarchy:

1. **BLOCKED** — At least one mandatory requirement has a `FAIL` decision.
2. **NEEDS_REVIEW** — No requirement has failed, but one or more requirements have `INSUFFICIENT_EVIDENCE`.
3. **READY** — All 12 mandatory requirements have passed.

---

## 5. Assessment Results — Release R2.4

### Execution Summary

The latest assessment evaluated all 12 mandatory requirements.

| Decision | Count |
|---|---:|
| PASS | 4 |
| FAIL | 5 |
| INSUFFICIENT_EVIDENCE | 3 |
| **Total** | **12** |

### Overall Decision: BLOCKED

The release is blocked because five mandatory requirements have evidence demonstrating violations or unmet acceptance criteria.

### Per-Requirement Assessment

| Requirement | Jira Key | Decision | Evidence and Reasoning |
|---|---|---|---|
| REQ-01 | TYN-89 | PASS | TYN-316: 146/146 mandatory regression cases passed on the target build. |
| REQ-02 | TYN-263 | FAIL | TYN-306: Cross-customer document exposure was confirmed. Defect ISO-DEF-12 was reopened. |
| REQ-03 | TYN-225 | INSUFFICIENT_EVIDENCE | TYN-26 used prompt p6 instead of target prompt p7. The 96.2% result does not establish compliance for p7. |
| REQ-04 | TYN-53 | PASS | TYN-150: Production p95 latency was 1.4 seconds, within the 2-second threshold. |
| REQ-05 | TYN-352 | FAIL | TYN-224: Mean model cost was USD 0.018 per request, exceeding the USD 0.012 threshold. |
| REQ-06 | TYN-73 | INSUFFICIENT_EVIDENCE | TYN-180 contains staging-only Security Owner approval. TYN-119 is Engineering Manager approval, not production Security Owner approval. |
| REQ-07 | TYN-329 | PASS | TYN-396: REDACT-901 explicitly supersedes REDACT-870; 28/28 redaction test cases passed. |
| REQ-08 | TYN-48 | FAIL | TYN-76: Zero of 12 escalated conversations reached the support queue. |
| REQ-09 | TYN-143 | FAIL | TYN-174: 214 session records were lost during a target-build rollback rehearsal. No explicit supersession was established. |
| REQ-10 | TYN-57 | PASS | TYN-9: PARSE-622 explicitly supersedes PARSE-601; 60/60 mandatory parsing cases passed. |
| REQ-11 | TYN-162 | INSUFFICIENT_EVIDENCE | TYN-259 contains developer-only local testing. TYN-102 contains QA evidence for R2.3, not the target R2.4 build. |
| REQ-12 | TYN-400 | FAIL | TYN-318: 49/50 tests passed; a duplicate final streaming message was detected. |

### Release Gate Conclusion

**4 PASS | 5 FAIL | 3 INSUFFICIENT_EVIDENCE**

**Final Release Decision: BLOCKED**

The release must not proceed until the mandatory failed requirements are resolved and the insufficient evidence requirements are verified.

---

## 6. Investigation Trace and Reporting

The application generates both human-readable and machine-readable reports in the `reports/` directory.

### TXT Report

The TXT report contains:

- Overall release decision.
- Requirement-level decisions.
- Evidence summaries and reasoning.
- Investigation trace.
- Applicable and excluded Jira evidence references.
- Runtime execution metrics.
- Model usage status.

### JSON Report

The JSON report contains structured assessment data, including:

- Target release configuration.
- Overall decision and reason.
- Requirement-level decisions.
- Applicable evidence records.
- Excluded evidence records and mismatch details.
- Investigation trace.
- Runtime metrics.
- Model usage information.
- Evaluation errors, where applicable.

### Investigation Trace

For every requirement, the trace records:

- Requirement ID.
- Requirement Jira issue key.
- Final decision.
- Applicable evidence issue keys.
- Excluded evidence issue keys.

This provides traceability between the final release decision and the Jira records used during evaluation.

### Runtime Metrics

The report includes:

- Total execution time.
- Number of requirements discovered.
- Number of requirements evaluated.
- Evaluation mode.
- Jira requirement search completion status.

### Model Usage

The current execution reports model usage as `not_invoked` because the deterministic evaluators produce the final requirement decisions.

Token usage is reported as unavailable rather than inventing token counts.

---

## 7. Installation and Execution

### Prerequisites

- Python 3.11 or later.
- Jira Cloud access to the assessment project.
- Network connectivity to the Jira instance.
- A Python virtual environment.
- Dependencies listed in `requirements-agent.txt`.

### Step 1: Navigate to the Project

```powershell
cd C:\YellowNetworksAssessment\ReleaseAgent
```

### Step 2: Activate the Virtual Environment

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies

```powershell
pip install -r requirements-agent.txt
```

### Step 4: Configure Jira Credentials

Create a `.env` file in the project root.

Configure the following variables using your own Jira credentials:

```ini
JIRA_BASE_URL=https://tyn-release-lab.atlassian.net
JIRA_EMAIL=your-jira-email
JIRA_API_TOKEN=your-jira-api-token
JIRA_PROJECT_KEY=TYN
```

**Security:** Never commit or share the `.env` file, Jira API token, or other credentials.

### Step 5: Run the Assessment (CLI)

```powershell
python agent.py
```

The application retrieves the Jira requirements, evaluates the 12 mandatory criteria, and generates the assessment reports.

### Step 5B: Launch the Interactive Streamlit UI

```powershell
.\venv\Scripts\streamlit.exe run app.py
```

This launches the interactive investigation interface in your web browser, allowing you to:
- Select individual requirements (e.g., REQ-02, REQ-04) to investigate linked Jira issues and commit metadata.
- View applicable evidence vs. excluded records with explicit mismatch field comparisons.
- Run the full 12-requirement release gate and export structured JSON reports.

### Step 6: Review Generated Reports

```powershell
Get-ChildItem .\reports\
```

Open the generated TXT or JSON report to inspect the assessment results.

---

## 8. Dependencies

The project uses pinned versions to improve reproducibility.

Dependencies are maintained in:

`requirements-agent.txt`

Install them using:

```powershell
pip install -r requirements-agent.txt
```

---

## 9. Security and Known Limitations

### Security Considerations

- Jira credentials are loaded through environment variables.
- Credentials should not be stored in source files or committed to version control.
- Jira is used as the evidence source for this assessment.
- Untrusted text inside evidence records cannot override deterministic evaluation rules.
- Release decisions are not based solely on Jira workflow status.

### Known Limitations

1. **Evidence Scope:** The system evaluates records available in the Jira assessment project. It does not independently inspect external CI/CD systems, deployment infrastructure, or live production telemetry.

2. **Text Extraction:** Evidence interpretation relies on structured text extraction and pattern-based parsing. Non-standard or ambiguous evidence may require additional normalization.

3. **Deterministic Evaluation:** Final decisions are generated by Python evaluators. The initialized LangGraph and Ollama components are not currently used to produce the final assessment decisions.

4. **Evidence Completeness:** The accuracy of the assessment depends on the completeness and correctness of the Jira evidence records and their relationships.

5. **Cost Evaluation:** Cost assessment uses the applicable rate card and measurements documented in the Jira evidence.

6. **Human Review:** Requirements classified as `INSUFFICIENT_EVIDENCE` require additional verification before release readiness can be established.

---

## 10. AI Assistance Disclosure

Generative AI assistance was used during development for support with Jira API integration, Python implementation, regex pattern design, debugging, and documentation.

The application includes LangGraph, LangChain Ollama, and a locally configured Qwen 2.5:3B model integration.

However, the current assessment execution does not invoke the LLM agent to produce final decisions.

All 12 final requirement decisions are generated using deterministic Python evaluation logic. This ensures that the release gate is based on explicit target validation, evidence checks, and requirement-specific rules rather than unverified LLM-generated conclusions.

---

## 11. Final Project Outcome

The Jira Release Evidence Agent successfully:

- Retrieved all 12 mandatory release requirements.
- Investigated linked Jira evidence and comments.
- Validated evidence against the target release configuration.
- Distinguished failures from insufficient evidence.
- Applied requirement-specific deterministic evaluation rules.
- Recorded applicable and excluded evidence references.
- Generated TXT and JSON assessment reports.
- Captured investigation traces and runtime metrics.

**Final Assessment Outcome: BLOCKED**

The assessment identified five mandatory release blockers and three requirements requiring additional evidence.

The generated reports provide an auditable basis for understanding the R2.4 release readiness decision.
