"""
PayTrust AI — Streamlit Local Prototype
Phase 1: Clean Local Foundation

Production-minded local prototype (Streamlit + SQLite).
AI-agent payment safety & authorization layer:
  Agent Intent → Policy → Risk → Evidence → AI Investigation → Simulation → ALLOW/ASK_USER/DENY → Payment

Run:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root on sys.path for `core` / `database` imports
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from core.config import get_settings
from core.logger import configure_root_logging, get_logger, new_request_id
from database.database import init_db, inspect_db

settings = get_settings()
logger = get_logger("app")
configure_root_logging()

# ── Page config must be first Streamlit call ──
st.set_page_config(
    page_title=f"{settings.APP_NAME} — Local Prototype",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Polished minimal CSS ──
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.mono { font-family: 'JetBrains Mono', monospace; }
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f766e 100%);
  color: white; padding: 1.75rem 1.5rem; border-radius: 16px; margin-bottom: 1rem;
}
.hero h1 { margin: 0; font-size: 1.9rem; font-weight: 700; }
.hero p { margin: .35rem 0 0; opacity: .9; font-size: .95rem; }
.metric-card {
  background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1rem 1.1rem;
}
.phase-badge {
  display: inline-block; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 999px;
  padding: .15rem .65rem; font-size: .78rem; color: #334155; margin-right: .35rem;
}
.status-ok { color: #059669; font-weight: 600; }
.status-warn { color: #d97706; font-weight: 600; }
a { text-decoration: none; }
</style>
""", unsafe_allow_html=True)

# ── Init DB on first run (idempotent, cached) ──
@st.cache_resource(show_spinner=False)
def _bootstrap_db():
    new_request_id()
    try:
        result = init_db(seed=True)
        logger.info(f"DB bootstrap {result}")
        return result
    except Exception as exc:
        logger.exception(f"DB init failed: {exc}")
        return {"error": str(exc)}

_boot = _bootstrap_db()
_db_info = inspect_db()

# ── Sidebar — polished navigation ──
with st.sidebar:
    st.markdown("### 🛡️ PayTrust AI")
    st.caption("AI-agent payment safety layer  •  local prototype")
    st.divider()

    nav = st.radio(
        "Navigate",
        [
            "Dashboard",
            "Agent Policy",
            "Payment Request",
            "Risk Assessment",
            "AI Investigation",
            "Decision Simulator",
            "Payment History",
            "Audit Log",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Environment**")
    st.code(f"{settings.ENVIRONMENT}  •  v{settings.APP_VERSION}", language="text")
    # DB health
    if _db_info.get("exists"):
        st.success(f"SQLite • {_db_info.get('size_bytes', 0):,} bytes", icon="✅")
        with st.expander("DB inspect", expanded=False):
            st.json({k: v for k, v in _db_info.items() if k not in ("db_path",)})
            st.caption(f"`{_db_info.get('db_path')}`")
    else:
        st.error("DB not initialized", icon="⚠️")

    # Config warnings
    warns = settings.validate_for_production()
    if warns:
        with st.expander("⚠️ Config warnings", expanded=False):
            for w in warns:
                st.warning(w)
    else:
        st.caption("Config OK")

    st.divider()
    st.caption("Phase 1 — Clean Local Foundation")
    st.caption("Next: Phase 2 SQLite persistence → Phase 3 Policy Engine")

# ── Header hero ──
st.markdown(f"""
<div class="hero">
  <h1>🛡️ {settings.APP_NAME} — Evidence-Driven Payment Safety</h1>
  <p>Controls how AI agents interact with payment systems: <b>Policy</b> → <b>Risk</b> → <b>Evidence</b> → <b>AI Investigation</b> → <b>ALLOW / ASK_USER / DENY</b></p>
</div>
""", unsafe_allow_html=True)
st.markdown(
    '<span class="phase-badge">Phase 1 ✓ Foundation</span>'
    '<span class="phase-badge">Streamlit + SQLite</span>'
    '<span class="phase-badge">Deterministic policy is final</span>'
    '<span class="phase-badge">LLM is advisory only</span>',
    unsafe_allow_html=True,
)
st.write("")

# ── Helpers ──
def _placeholder(title: str, desc: str, phase: str):
    st.info(f"**{title}** — {desc}  \n*Available in {phase}.*", icon="🚧")
    st.caption("Build in small, independently testable milestones — deterministic policy remains the final enforcement layer.")

# ── Pages ──
if nav == "Dashboard":
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("DB Tables", len(_db_info.get("tables", [])), border=True)
    with col2:
        st.metric("Users (seed)", _db_info.get("counts", {}).get("users", 0), border=True)
    with col3:
        st.metric("Agents (seed)", _db_info.get("counts", {}).get("agents", 0), border=True)
    with col4:
        st.metric("Merchants (seed)", _db_info.get("counts", {}).get("merchants", 0), border=True)

    st.write("")
    left, right = st.columns([2, 1])
    with left:
        st.subheader("System Health")
        health = [
            ("Streamlit", "OK", "App renders without errors"),
            ("SQLite", "OK" if _db_info.get("exists") else "PENDING", _db_info.get("db_path", "")),
            ("Config", "OK" if not warns else "WARN", ", ".join(warns) if warns else "Validated"),
            ("Policy Engine", "PHASE 3", "Deterministic — LLM never overrides"),
            ("Risk Engine", "PHASE 5", "Transparent rules first, ML later"),
            ("AI Engine", "PHASE 9", "OpenRouter → Groq → Gemini → fallback"),
            ("Razorpay", "PHASE 11", "Test Mode only, secrets in .env"),
        ]
        st.table(
            {"Component": [h[0] for h in health], "Status": [h[1] for h in health], "Detail": [h[2] for h in health]}
        )
    with right:
        st.subheader("Architecture")
        st.markdown("""
**Flow (differentiator):**
```
AI Agent → Intent → Authorization → Policy
→ Risk → Evidence → AI Investigation
→ Decision Simulation → ALLOW / ASK / DENY
→ Payment (Test Mode)
```
""")
        st.caption("Core question: *Should this agent be allowed to make this payment on behalf of the user?*")
        with st.expander("Tech stack — Phase 1", expanded=False):
            st.markdown("""
- **UI:** Streamlit 1.39
- **Lang:** Python 3.11/3.12
- **DB:** SQLite (WAL, parameterized SQL)
- **ML:** scikit-learn (later)
- **AI:** OpenRouter primary → Groq → Gemini → deterministic
- **Payments:** Razorpay Test Mode (Phase 11)
- **Config:** python-dotenv + pydantic-settings
""")

    st.divider()
    st.subheader("What Phase 1 delivers")
    a, b, c = st.columns(3)
    with a:
        st.markdown("**✓ Runnable locally**  \n`streamlit run app.py` with no Docker, Postgres, Redis, or cloud.  \nVirtual env + `requirements.txt` + `.env.example` + `.gitignore`.")
    with b:
        st.markdown("**✓ Centralized config**  \n`core/config.py` validates env, supports `sqlite:///` default, warns on default secrets.  \n`core/logger.py` redacts keys, adds request_id.")
    with c:
        st.markdown("**✓ SQLite ready**  \n`database/database.py` idempotent `init_db()` with seed user/agent/merchants, WAL, FK, inspection util.  \nEngines stubbed for Phase 3-6.")

elif nav == "Agent Policy":
    st.subheader("Agent Policy — Authorization Layer")
    st.caption("Deterministic policy is the final enforcement layer. LLM never overrides it. (Phase 3)")
    _placeholder("Policy Engine", "Daily limit ₹100k, max txn ₹60k, approval >₹30k, allowed electronics/books/travel, blocked gambling/financial. Returns {authorized, requires_approval, violations[], reasons[]}.", "Phase 3")
    with st.expander("Seed policy preview", expanded=True):
        st.markdown("""
| Field | Value |
|-------|-------|
| User | Test User (`test@paytrust.ai`) |
| Agent | Shopping Assistant |
| Daily limit | ₹100,000 |
| Max transaction | ₹60,000 |
| Approval required | > ₹30,000 |
| Allowed | electronics, books, travel |
| Blocked | gambling, financial_products |
""")
        st.code("policy_engine.evaluate(user, agent, amount, category, merchant) -> {authorized, requires_approval, violations}", language="python")

elif nav == "Payment Request":
    st.subheader("Payment Request — Standardized Input")
    st.caption("Every AI-agent intent becomes a validated `PaymentRequest` before policy/risk evaluation. (Phase 4)")
    _placeholder("Payment Request Model", "Validates request_id, user_id, agent_id, merchant_id, amount≥1, currency=INR, category enum, rejects negatives/missing/invalid.", "Phase 4")
    with st.form("preview_payment_request"):
        st.write("**Preview form (wired in Phase 4)**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.text_input("request_id", placeholder="req_abc123", disabled=True)
            st.number_input("amount (INR)", min_value=0, value=54999, disabled=True)
        with c2:
            st.selectbox("category", ["electronics", "books", "travel", "gambling"], disabled=True)
            st.text_input("merchant_name", value="TechMart Electronics", disabled=True)
        with c3:
            st.text_input("agent", value="Shopping Assistant", disabled=True)
            st.text_area("agent_reason", value="User requested laptop purchase", disabled=True)
        st.form_submit_button("Validate & Evaluate (Phase 4)", disabled=True)

elif nav == "Risk Assessment":
    st.subheader("Risk Assessment — Transparent Deterministic Rules")
    st.caption("Risk dimensions: amount, spending behavior, merchant, policy, agent auth, frequency, history → `risk_score 0-100 + factors`. (Phase 5)")
    _placeholder("Risk Engine", "Lightweight deterministic rules first; ML (Isolation Forest/XGBoost) only if demonstrably better. Explains contributions.", "Phase 5")
    with st.expander("Risk dimensions"):
        st.markdown("- Amount risk  \n- Spending behavior  \n- Merchant risk  \n- Policy risk  \n- Agent authorization  \n- Transaction frequency  \n- Historical behavior")

elif nav == "AI Investigation":
    st.subheader("AI Investigation — Evidence-Driven, Advisory Only")
    st.caption("AI receives structured facts (policy_result, risk_factors, history, decision candidate) and produces explanation — never executes payment. (Phase 9)")
    _placeholder("AI Engine", "Provider priority: OpenRouter → Groq → Gemini → deterministic fallback. Strict prompts, structured output, no invented facts.", "Phase 9")
    st.warning("Safety invariant: **Deterministic policy/risk is final. LLM is investigation/explanation assistant.**", icon="🔒")

elif nav == "Decision Simulator":
    st.subheader("Decision Simulator — Counterfactual Intelligence")
    st.caption("Core differentiator: *What happens if we ALLOW / ASK_USER / DENY?* Compare friction, exposure, business impact. (Phase 10)")
    _placeholder("Decision Engine + Simulator", "Rules: LOW+pass→ALLOW, MEDIUM+pass→ASK_USER, HIGH→DENY, violation→DENY. Simulated costs labeled **SIMULATED/ESTIMATED**.", "Phases 6 & 10")
    with st.columns(3)[0]:
        st.metric("ALLOW", "→ low friction", border=True)
    with st.columns(3)[1]:
        st.metric("ASK_USER", "→ review cost", border=True)
    with st.columns(3)[2]:
        st.metric("DENY", "→ safest", border=True)

elif nav == "Payment History":
    st.subheader("Payment History")
    st.caption("Local persistence view over `payment_requests` + `decisions` + `risk_assessments`. (Phase 2/7)")
    if _db_info.get("counts", {}).get("payment_requests", 0) == 0:
        _placeholder("Payment History", "Tables exist but empty until Phase 2 tests insert sample transactions; Phase 8 adds `data/synthetic_transactions.csv`.", "Phases 2 & 8")
    # Show empty table placeholder
    st.dataframe(
        [{"request_id": "—", "agent": "—", "merchant": "—", "amount": "—", "decision": "—", "risk": "—"}],
        use_container_width=True,
    )
    st.caption("Phase 2 will add DB unit tests: insert/read/update/invalid/relations/persistence-after-restart.")

elif nav == "Audit Log":
    st.subheader("Audit Log — Verifiable Decisions")
    st.caption("Every decision logs `request_id, event_type, decision, risk_score, processing_time`. No secrets. (Phases 13 & 15)")
    _placeholder("Audit Log", "Structured logging + dashboard: total/ALLOW/ASK/DENY, avg risk, high-risk, violations, AI failures.", "Phases 13 & 15")
    with st.expander("DB tables initialized"):
        st.json(_boot if isinstance(_boot, dict) else {"raw": str(_boot)})

# ── Footer ──
st.divider()
st.caption(
    "PayTrust AI — production-minded local prototype. Phase 1 complete.  \n"
    "Existing `ai-payment-copilot/` FastAPI+Postgres+React track preserved for production deployment — new `paytrust-ai/` Streamlit+SQLite track is the local MVP harness sharing the same engine logic."
)
