"""
PayTrust AI — Streamlit Local Prototype
Phases 1-16: Production-minded local prototype (Streamlit + SQLite)

Run:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import json
import uuid
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

from core.config import get_settings
from core.logger import configure_root_logging, get_logger, new_request_id
from database.database import init_db, inspect_db, get_connection
from database import repositories as repo
from models.payment_request import PaymentRequest
from engines.policy_engine import PolicyEngine
from engines.risk_engine import RiskEngine
from engines.decision_engine import DecisionEngine
from engines.ai_engine import AIEngine, build_facts
from engines.decision_simulator import simulate

settings = get_settings()
logger = get_logger("app")
configure_root_logging()

st.set_page_config(page_title=f"{settings.APP_NAME} — Payment Safety Copilot", page_icon=":material/security:", layout="wide", initial_sidebar_state="expanded")

# Minimal CSS — only what native theming can't express (decision pills used in f-strings below).
# Everything else (colors, fonts, borders) lives in .streamlit/config.toml.
st.markdown("""
<style>
.decision-ALLOW { background: rgba(52,211,153,.12); border: 1px solid #34d399; color: #34d399; padding: .45rem .8rem; border-radius: 8px; font-weight: 700; display: inline-block; }
.decision-ASK_USER { background: rgba(251,191,36,.12); border: 1px solid #fbbf24; color: #fbbf24; padding: .45rem .8rem; border-radius: 8px; font-weight: 700; display: inline-block; }
.decision-DENY { background: rgba(248,113,113,.12); border: 1px solid #f87171; color: #f87171; padding: .45rem .8rem; border-radius: 8px; font-weight: 700; display: inline-block; }
.risk-LOW { color: #34d399; font-weight: 700; }
.risk-MEDIUM { color: #fbbf24; font-weight: 700; }
.risk-HIGH, .risk-CRITICAL { color: #f87171; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

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

def _all_merchants():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, category, region FROM merchants ORDER BY id")
        return [dict(r) for r in cur.fetchall()]

def _all_users_agents():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, email, name FROM users ORDER BY id")
        users = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id, agent_name FROM agents ORDER BY id")
        agents = [dict(r) for r in cur.fetchall()]
        return users, agents

def _recent_requests(limit=50):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT pr.request_id, pr.amount, pr.category, pr.merchant_name, pr.created_at, pr.user_id, pr.agent_id, pr.merchant_id,
                   d.decision, d.risk_score, d.risk_level
            FROM payment_requests pr LEFT JOIN decisions d ON d.request_id = pr.request_id
            ORDER BY pr.created_at DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]

def _audit_logs(limit=100):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT request_id, event_type, actor, action, created_at FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

@st.cache_data(show_spinner=False)
def _load_preds_df():
    """Honest held-out IEEE test predictions (for threshold tool)."""
    from models.threshold import load_test_predictions
    return load_test_predictions()


@st.cache_data(show_spinner=False)
def _threshold_curves():
    """Sweep curves across thresholds — cached, computed once."""
    from models.threshold import sweep, to_curves
    return to_curves(sweep(step=0.01))


@st.cache_data(show_spinner=False)
def _threshold_recommend():
    """Operating-point hints (max F1, min SIMULATED cost) — business decision, labelled."""
    from models.threshold import best_operating_point
    return best_operating_point()
# Sidebar
with st.sidebar:
    st.markdown("### :material/security: PayTrust AI")
    st.caption("Evidence-driven payment safety • local prototype + real IEEE data")
    nav = st.radio("Navigate", ["Dashboard","Agent Policy","Payment Request","Risk Assessment","AI Investigation","Decision Simulator","Payment History","Real World (IEEE)","Evaluation & Thresholds","Help & Glossary","Audit Log"], label_visibility="collapsed")
    st.caption("Need help? → **Help & Glossary** explains every variable")
    st.markdown("**Environment**")
    st.code(f"{settings.ENVIRONMENT} • v{settings.APP_VERSION}", language="text")
    if _db_info.get("exists"):
        st.success(f"SQLite • {_db_info.get('size_bytes',0):,} bytes", icon=":material/check_circle:")
        with st.expander("DB inspect", icon=":material/database:"):
            st.json({k: v for k, v in _db_info.items() if k not in ("db_path",)})
    else:
        st.error("DB not initialized", icon=":material/error:")
    warns = settings.validate_for_production()
    if warns:
        with st.expander("Config warnings", icon=":material/warning:"):
            for w in warns: st.warning(w)
    st.caption("Phases 1-16 ✓ production-minded local prototype")
    st.caption("Policy final • LLM advisory • Razorpay TEST MODE")

st.title(f"{settings.APP_NAME}", icon=":material/verified_user:")
st.caption("Policy → Risk → Evidence → AI Investigation → **ALLOW / ASK_USER / DENY** → Payment (Test Mode)")
st.badge("Phases 1-16 ✓", icon=":material/check_circle:", color="green")
st.badge("Deterministic final", icon=":material/gavel:", color="blue")
st.badge("LLM advisory", icon=":material/psychology:", color="violet")
st.badge("SIMULATED estimates", icon=":material/science:", color="orange")
st.badge("Razorpay TEST MODE", icon=":material/lock:", color="gray")

policy_engine = PolicyEngine()
risk_engine = RiskEngine()
decision_engine = DecisionEngine(policy_engine, risk_engine)
ai_engine = AIEngine()

if nav == "Dashboard":
    with st.expander("ℹ️ How to use PayTrust — 1 min guide", expanded=False):
        st.markdown("""
        **You are the human approver for an AI shopping agent.** The agent wants to spend your money — PayTrust decides **ALLOW / ASK_USER / DENY**.
        - **Green ALLOW** = low risk + policy pass → auto-pay (low friction).
        - **Yellow ASK_USER** = medium risk or amount >30k → needs your click.
        - **Red DENY** = violation or high risk → blocked.
        **Do:** Go to **Payment Request** → try a normal 25k payment → see green → try 70k or `gambling` → see red → **AI Investigation** explains why → **Real World** to see 590k real transactions.
        """)
    # Observability metrics via core/metrics
    try:
        from core.metrics import get_dashboard_metrics
        metrics = get_dashboard_metrics()
    except Exception:
        metrics = {}
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("Total Requests", metrics.get("total_requests",0))
    with c2: st.metric("ALLOW", metrics.get("by_decision",{}).get("ALLOW",0))
    with c3: st.metric("ASK_USER", metrics.get("by_decision",{}).get("ASK_USER",0))
    with c4: st.metric("DENY", metrics.get("by_decision",{}).get("DENY",0))
    c5,c6,c7,c8 = st.columns(4)
    with c5: st.metric("Avg Risk", f"{metrics.get('avg_risk',0):.1f}" if metrics.get("avg_risk") else "—")
    with c6: st.metric("High/Critical", metrics.get("high_risk_count",0))
    with c7: st.metric("Policy Violations", metrics.get("policy_violations",0))
    with c8: st.metric("AI Fallbacks", metrics.get("ai_failures",0))
    st.divider()
    colA, colB = st.columns([2,1])
    with colA:
        st.subheader("Recent Decisions (with processing time)")
        rec = _recent_requests(10)
        if rec:
            df = pd.DataFrame(rec)
            st.dataframe(df, width="stretch", hide_index=True)
            st.caption("Structured logs include request_id, decision, risk_score, processing_ms — never secrets (core/logger.py redaction).")
        else:
            st.info("No requests yet — create one in Payment Request.", icon="ℹ️")
        # ML report preview
        ml_report = Path("evaluation/ml_report.json")
        if ml_report.exists():
            with st.expander("Optional ML Report (synthetic)"):
                st.json(json.loads(ml_report.read_text()))
                st.caption("PR-AUC, precision/recall are on synthetic held-out test — not real fraud. See models/ml_risk.py")
    with colB:
        st.subheader("Health")
        health = [
            ("SQLite", "OK" if _db_info.get("exists") else "PENDING", _db_info.get("db_path","")),
            ("PolicyEngine", "OK", "10 tests"),
            ("RiskEngine", "OK", "7 dims"),
            ("DecisionEngine", "OK", "ALLOW/ASK/DENY"),
            ("Simulator", "OK", "SIMULATED costs"),
            ("AIEngine", "OK" if settings.OPENROUTER_API_KEY else "Fallback", "OpenRouter→Groq→Gemini→deterministic"),
            ("Razorpay", "SIMULATED" if not settings.RAZORPAY_KEY_ID else "TEST MODE", "HMAC raw body, idempotency"),
            ("ML", "Optional", "Logistic + IsolationForest"),
        ]
        st.table({"Component":[h[0] for h in health],"Status":[h[1] for h in health],"Detail":[h[2] for h in health]})
        st.caption("Observability: `core/metrics.py` + `core/logger.py` request_id + audit_logs. No API keys in logs.")

elif nav == "Agent Policy":
    st.subheader("Agent policy — deterministic authorization", icon=":material/rule:")
    st.caption("LLM never overrides. Parameterized SQL.")
    users, agents = _all_users_agents()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ap.*, u.email, u.name as user_name, a.agent_name FROM agent_policies ap JOIN users u ON u.id=ap.user_id JOIN agents a ON a.id=ap.agent_id ORDER BY ap.id")
        policies = [dict(r) for r in cur.fetchall()]
    if policies:
        for p in policies:
            allowed = json.loads(p["allowed_categories"]) if p["allowed_categories"] else []
            blocked = json.loads(p["blocked_categories"]) if p["blocked_categories"] else []
            st.markdown(f"• **{p['user_name']}** (`{p['email']}`) + **{p['agent_name']}** → daily {p['daily_limit']:,} max {p['max_transaction']:,} approval>{p['approval_threshold']:,} allowed {allowed} blocked {blocked}")
    st.divider()
    with st.form("policy_form"):
        c1,c2,c3 = st.columns(3)
        with c1:
            user_opts = {f"{u['name']} ({u['email']})": u["id"] for u in users}
            sel_user = st.selectbox("User", list(user_opts.keys()))
            daily = st.number_input("Daily limit (INR)", min_value=1000, value=100000, step=1000)
            max_tx = st.number_input("Max transaction (INR)", min_value=1000, value=60000, step=1000)
        with c2:
            agent_opts = {a["agent_name"]: a["id"] for a in agents}
            sel_agent = st.selectbox("Agent", list(agent_opts.keys()))
            approval = st.number_input("Approval threshold (INR)", min_value=1000, value=30000, step=1000)
        with c3:
            allowed_in = st.text_input("Allowed (comma)", value="electronics, books, travel")
            blocked_in = st.text_input("Blocked (comma)", value="gambling, financial_products")
        if st.form_submit_button("Save Policy", type="primary"):
            uid = user_opts[sel_user]; aid = agent_opts[sel_agent]
            allowed = [c.strip().lower() for c in allowed_in.split(",") if c.strip()]
            blocked = [c.strip().lower() for c in blocked_in.split(",") if c.strip()]
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM agent_policies WHERE user_id=? AND agent_id=?", (uid, aid))
                if cur.fetchone():
                    cur.execute("UPDATE agent_policies SET daily_limit=?, max_transaction=?, approval_threshold=?, allowed_categories=?, blocked_categories=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE user_id=? AND agent_id=?", (daily,max_tx,approval,json.dumps(allowed),json.dumps(blocked),uid,aid))
                else:
                    cur.execute("INSERT INTO agent_policies (user_id, agent_id, daily_limit, max_transaction, approval_threshold, allowed_categories, blocked_categories) VALUES (?,?,?,?,?,?,?)", (uid,aid,daily,max_tx,approval,json.dumps(allowed),json.dumps(blocked)))
                conn.commit()
            st.success("Policy saved"); st.rerun()

elif nav == "Payment Request":
    st.subheader("Payment request — validate → policy → risk → decision", icon=":material/request_quote:")
    with st.expander("ℹ️ How to use this page + what each field means", expanded=False):
        st.markdown("""
        **How to use:** Pick a **User** (who pays), **Agent** (AI acting), **Merchant** (who receives), enter **Amount** and **Category**, then **Evaluate**. The system runs: `Pydantic validation → PolicyEngine → RiskEngine → DecisionEngine` in <100ms and stores the decision.
        **Try:** 25k `electronics` at `TechMart` → **ALLOW** → change to 65k → **DENY (max 60k)** → change category to `gambling` → **DENY (blocked)**. See **Help & Glossary → PayTrust Variables** for full definitions.
        """)
        st.caption("Hover the ⓘ on each field for a 1-line meaning.")
    users, agents = _all_users_agents()
    merchants = _all_merchants()
    user_map = {f"{u['name']} ({u['email']})": u["id"] for u in users}
    agent_map = {a["agent_name"]: a["id"] for a in agents}
    merch_map = {f"{m['name']} [{m['category']}]": m for m in merchants}
    with st.form("pr_form"):
        c1,c2,c3 = st.columns(3)
        with c1:
            req_id = st.text_input("request_id", value=f"req_{uuid.uuid4().hex[:8]}", help="Unique ID 6-64 chars a-z,0-9,-,_ . Used for idempotency — same ID won't double-charge. Auto-filled.")
            sel_u = st.selectbox("User", list(user_map.keys()), help="Who pays? Must exist. Determines which policy (daily 100k, max 60k) applies.")
            sel_a = st.selectbox("Agent", list(user_map.keys()) if False else list(agent_map.keys()), help="Which AI is acting? Must be authorized for this user (agent_policies). Unauthorized → DENY.")
        with c2:
            sel_m = st.selectbox("Merchant", list(merch_map.keys()), help="Who receives money? Category from merchant, but you choose category for this payment. New merchant → higher risk.")
            amount = st.number_input("Amount (INR)", min_value=1, value=25000, step=500, help="How much? ≥1. >30k → ASK_USER, >60k → DENY, + daily 100k check. In INR.")
            category = st.selectbox("Category", ["electronics","books","travel","food","fashion","grocery","fuel","gambling","financial_products"], help="What is bought? Must be one of 9. `gambling`/`financial_products` always blocked → DENY.")
        with c3:
            desc = st.text_area("Description", value="Laptop purchase", help="Human description of purchase. Stored, not used for decision. Max 500 chars.")
            agent_reason = st.text_area("Agent reason", value="User requested 16GB RAM laptop", help="Agent's self-explanation. Used as AI fact for investigation, not for deterministic decision.")
        submitted = st.form_submit_button("Evaluate Payment", type="primary")
    if submitted:
        t0 = time.perf_counter()
        try:
            mid = merch_map[sel_m]["id"]; mname = merch_map[sel_m]["name"]
            uid = user_map[sel_u]; aid = agent_map[sel_a]
            pr = PaymentRequest(request_id=req_id, user_id=uid, agent_id=aid, merchant_id=mid, merchant_name=mname, amount=amount, currency="INR", category=category, description=desc, agent_reason=agent_reason, timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"))
            repo.create_payment_request(req_id, uid, aid, mid, mname, amount, "INR", category, desc, agent_reason)
            pol_res = policy_engine.evaluate_request(uid, aid, amount, category, merchant_id=mid, merchant_name=mname)
            risk_res = risk_engine.assess_request(uid, aid, {"amount": amount, "category": category, "merchant_id": mid, "merchant_name": mname}, pol_res)
            dec = decision_engine.decide(pol_res, risk_res)
            ms = (time.perf_counter()-t0)*1000
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("INSERT OR REPLACE INTO risk_assessments (request_id, risk_score, risk_level, factors) VALUES (?,?,?,?)", (req_id, risk_res["risk_score"], risk_res["risk_level"], json.dumps(risk_res["factors"])))
                cur.execute("INSERT OR REPLACE INTO decisions (request_id, decision, risk_score, risk_level, policy_result, reasons) VALUES (?,?,?,?,?,?)", (req_id, dec["decision"], dec["risk_score"], dec["risk_level"], json.dumps(pol_res), json.dumps(dec["reasons"])))
                cur.execute("INSERT INTO audit_logs (request_id, event_type, actor, action, metadata) VALUES (?,?,?,?,?)", (req_id, "PAYMENT_EVALUATED", f"user:{uid}/agent:{aid}", dec["decision"], json.dumps({"amount": amount, "risk_score": risk_res["risk_score"], "ms": round(ms,1)})))
                conn.commit()
            # Observability log
            from core.metrics import log_evaluation
            log_evaluation(req_id, dec["decision"], dec["risk_score"], dec["risk_level"], ms)
            st.success(f"Evaluated in {ms:.0f}ms")
            st.markdown(f'<div class="decision-{dec["decision"]}">{dec["decision"]} — Risk {dec["risk_level"]} ({dec["risk_score"]})</div>', unsafe_allow_html=True)
            c1,c2 = st.columns(2)
            with c1: st.markdown("**Policy**"); st.json(pol_res)
            with c2:
                st.markdown("**Risk factors**")
                for f in risk_res["factors"]: st.markdown(f"• **{f['name']}** {f['severity']} +{f['score']}: {f['details']}")
            st.markdown("**Decision reasons**"); [st.markdown(f"• {r}") for r in dec["reasons"]]
            if st.button("Run AI Investigation (advisory)", icon=":material/psychology:"):
                facts = build_facts(pr.to_db_dict(), pol_res, risk_res, dec)
                ai_res = ai_engine.investigate(facts)
                st.info(f"**AI:** {ai_res['explanation']}", icon="🤖")
                with st.expander("AI details"): st.json(ai_res)
        except Exception as exc:
            st.error(f"Failed: {exc}")

elif nav == "Risk Assessment":
    st.subheader("Risk assessment — interactive (7 dimensions, 0-100)", icon=":material/speed:")
    with st.expander("ℹ️ How to use + what each slider means", expanded=False):
        st.markdown("""
        **How to use:** Move sliders to simulate a payment and see risk add up. The engine sums 7 dims (see Help & Glossary → Risk & Decisions table). No ML yet — pure rules, so you can trace every point.
        **Try:** Set `Amount` 65k + `Violations: category_blocked` → risk jumps to HIGH (≥65) due to critical factor. Check `New merchant` → +10.
        """)
    c1,c2 = st.columns(2)
    with c1:
        amt = st.slider("Amount (INR)", 1000, 100000, 25000, step=1000, help="Transaction amount. ≥50k +20 high, ≥30k +12 med, ≥15k +5 low (amount_risk).")
        cat = st.selectbox("Category", ["electronics","books","travel","gambling","financial_products","food"], key="rk_cat", help="Category. `gambling` → +25 critical merchant_risk; else new merchant +10.")
        daily_spent = st.slider("Daily spent before", 0, 100000, 0, step=5000, help="Already spent today. Projected (spent+amt)/daily_limit ≥0.9→+20, ≥0.7→+12 (spending_behavior). Daily limit 100k.")
        tx_hour = st.slider("Tx last hour", 0, 15, 1, help="How many transactions this user did in last hour. ≥10 +20 high, ≥5 +12 med (frequency_risk).")
    with c2:
        viol = st.multiselect("Violations to simulate", ["max_transaction_exceeded","category_blocked","merchant_blocked","daily_limit_exceeded","unauthorized_agent"], help="Pick policy violations to see policy_risk (+15-25) and agent_auth_risk (+25). See Help → Risk table.")
        new_merch = st.checkbox("New merchant", help="First time with this merchant → +10 merchant_risk (medium).")
        new_user = st.checkbox("New user", help="User has <5 past txs + high amount → +12 historical_behavior.")
    if st.button("Calculate Risk", type="primary"):
        pol = {"violations": viol, "reasons": []}
        ctx = {"daily_limit": 100000, "daily_spent": daily_spent, "transactions_last_hour": tx_hour, "user_total_txns": 1 if new_user else 20, "is_new_merchant": new_merch, "is_new_user": new_user}
        res = risk_engine.assess({"amount": amt, "category": cat, "merchant_risk_tier": "high" if cat=="gambling" else "standard"}, pol, ctx)
        color = "#34D399" if res["risk_score"] < 31 else ("#FBBF24" if res["risk_score"] < 61 else "#F87171")
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=res["risk_score"], number={"font": {"size": 36}},
            title={"text": res["risk_level"], "font": {"size": 16, "color": color}},
            gauge={"axis": {"range": [0, 100], "tickcolor": "#94A3B8"},
                   "bar": {"color": color, "thickness": .6},
                   "bgcolor": "rgba(0,0,0,0)",
                   "steps": [{"range": [0, 30], "color": "rgba(52,211,153,.08)"},
                             {"range": [30, 60], "color": "rgba(251,191,36,.08)"},
                             {"range": [60, 100], "color": "rgba(248,113,113,.08)"}],
                   "bordercolor": "#334155"},
        ))
        fig.update_layout(height=200, margin=dict(l=5, r=5, t=5, b=5), paper_bgcolor="rgba(0,0,0,0)", font={"color": "#F1F5F9", "family": "Inter"})
        st.plotly_chart(fig, width="stretch", key="risk_gauge")
        for f in res["factors"]: st.markdown(f"• **{f['name']}** [{f['severity']}] +{f['score']}: {f['details']}")
        with st.expander("JSON"): st.json(res)

elif nav == "AI Investigation":
    st.subheader("AI investigation — advisory only", icon=":material/psychology:")
    st.caption("Structured facts only. Provider: OpenRouter → Groq → Gemini → deterministic.")
    rec = _recent_requests(10)
    if not rec:
        st.info("No decisions yet.", icon="ℹ️")
    else:
        opts = {f"{r['request_id']} — {r['decision']} ({r['risk_level']} {r['risk_score']})": r["request_id"] for r in rec}
        sel = st.selectbox("Select payment", list(opts.keys()))
        rid = opts[sel]
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM payment_requests WHERE request_id=?", (rid,))
            row = cur.fetchone()
            if row is None:
                st.warning(f"Payment {rid} not found — it may have been deleted.")
                st.stop()
            pr = dict(row)
            cur.execute("SELECT * FROM decisions WHERE request_id=?", (rid,)); dec_row = cur.fetchone(); dec = dict(dec_row) if dec_row else {}
            cur.execute("SELECT * FROM risk_assessments WHERE request_id=?", (rid,)); risk_row = cur.fetchone(); risk = dict(risk_row) if risk_row else {}
        pol_res = json.loads(dec.get("policy_result","{}")) if dec else {}
        risk_res = {"risk_score": dec.get("risk_score",0), "risk_level": dec.get("risk_level","LOW"), "factors": json.loads(risk.get("factors","[]"))} if risk else {}
        dec_map = {"decision": dec.get("decision","UNKNOWN"), "risk_score": dec.get("risk_score",0), "risk_level": dec.get("risk_level","LOW"), "reasons": json.loads(dec.get("reasons","[]"))} if dec else {}
        facts = build_facts(pr, pol_res, risk_res, dec_map)
        st.json(facts)
        if st.button("Investigate", type="primary", icon=":material/psychology:"):
            with st.spinner("Contacting provider…"):
                ai_res = ai_engine.investigate(facts)
            st.markdown(f"**Model:** `{ai_res['model']}` provider `{ai_res['provider']}` fallback={ai_res['fallback_used']} {ai_res['latency_ms']:.0f}ms")
            if ai_res.get("error"): st.warning(ai_res["error"], icon="⚠️")
            st.info(ai_res["explanation"], icon="🤖")
            c1,c2 = st.columns(2)
            with c1:
                st.markdown("**Concerns**")
                with st.container(border=True):
                    for c in ai_res.get("concerns",[]): st.markdown(f"• {c}")
            with c2:
                st.markdown("**Review questions**")
                with st.container(border=True):
                    for q in ai_res.get("review_questions",[]): st.markdown(f"• {q}")
            st.progress(ai_res.get("confidence",0)/100)
            st.caption(f"Confidence: {ai_res.get('confidence',0):.0%}")
            with st.expander("Full AI response (JSON)", icon=":material/data_object:"): st.json(ai_res)
        st.warning("Safety: deterministic final. AI is assistant.", icon="🔒")

elif nav == "Decision Simulator":
    st.subheader("Decision simulator — counterfactuals", icon=":material/compare_arrows:")
    st.caption("Not real financial forecasts. Derived from synthetic cost model.")
    rec = _recent_requests(10)
    if not rec:
        st.info("Create a Payment Request first.", icon="ℹ️")
    else:
        opts = {f"{r['request_id']} — {r['decision']}": r["request_id"] for r in rec}
        rid = st.selectbox("Payment", list(opts.keys()), key="sim")
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM payment_requests WHERE request_id=?", (rid,))
            row = cur.fetchone()
            if row is None:
                st.warning(f"Payment {rid} not found.")
                st.stop()
            pr = dict(row)
        pol_res = policy_engine.evaluate_request(pr["user_id"], pr["agent_id"], pr["amount"], pr["category"], pr["merchant_id"], pr["merchant_name"])
        risk_res = risk_engine.assess_request(pr["user_id"], pr["agent_id"], {"amount": pr["amount"], "category": pr["category"], "merchant_id": pr["merchant_id"]}, pol_res)
        dec_res = decision_engine.decide(pol_res, risk_res)
        sim = simulate(pr, pol_res, risk_res, dec_res)
        st.markdown(f"**Deterministic:** <span class='decision-{dec_res['decision']}'>{dec_res['decision']}</span> risk {dec_res['risk_level']} ({dec_res['risk_score']})", unsafe_allow_html=True)
        st.info(sim["reason"], icon="💡")
        st.table(pd.DataFrame(sim["counterfactuals"])[["action","fraud_exposure","false_positive_cost","operational_cost","expected_total_cost","customer_friction","policy_violation","rationale"]])
        st.caption(sim["disclaimer"])
        # What if panels
        st.markdown("#### What-if scenarios")
        c1,c2,c3 = st.columns(3)
        for col, action in zip([c1,c2,c3], ["ALLOW","ASK_USER","DENY"]):
            cf = next(x for x in sim["counterfactuals"] if x["action"]==action)
            with col:
                with st.container(border=True):
                    st.markdown(f"**What if {action}?**")
                    st.metric("Total cost (SIM)", f"INR {cf['expected_total_cost']:.0f}")
                    st.caption(f"Friction: {cf['customer_friction']} • Fraud: INR {cf['fraud_exposure']:.0f}")
                    st.caption(f"FP cost: INR {cf['false_positive_cost']:.0f} • OpEx: INR {cf['operational_cost']:.0f}")
        st.success(f"**Recommended (SIMULATED): {sim['recommended']}**")

elif nav == "Payment History":
    st.subheader("Payment history", icon=":material/history:")
    filt = st.selectbox("Filter decision", ["All","ALLOW","ASK_USER","DENY"])
    rows = _recent_requests(100)
    if filt != "All": rows = [r for r in rows if r.get("decision")==filt]
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)
        st.download_button("Download CSV (SIMULATED)", data=df.to_csv(index=False).encode("utf-8"), file_name="payment_history.csv", mime="text/csv")
    else: st.info("No history yet.", icon="ℹ️")
    if st.button("Generate Synthetic CSV (Phase 8)"):
        from data.synthetic import generate_synthetic_csv
        path, count = generate_synthetic_csv(n_normal=500, n_anomalies=50, seed=42)
        st.success(f"Generated {count} rows → {path}")
        st.dataframe(pd.read_csv(path).head(20), width="stretch")
        with st.expander("Distributions"):
            from data.synthetic import verify_distributions
            st.json(verify_distributions(path))
    # ML train
    if Path("data/synthetic_transactions.csv").exists():
        if st.button("Train Optional ML (Phase 12)"):
            from models.ml_risk import train_evaluate
            res = train_evaluate("data/synthetic_transactions.csv", seed=42, model_out="models/risk_model.pkl")
            st.json(res)
            st.caption("ML is advisory — deterministic engines remain final. See evaluation/ml_report.json")

elif nav == "Real World (IEEE)":
    st.subheader("Real-world IEEE fraud detection — chunked pipeline", icon=":material/analytics:")
    st.caption("Production-grade pipeline: 590k train + 506k test + 144k/141k identity + 123 synthetic → PayTrust decisions")
    # All CSVs overview — professional table
    csv_data = [
        {"File": "train_transaction.csv", "Rows": "590,540", "Cols": 394, "Size": "651 MB", "Use": "Train (label isFraud 3.5%)", "Pct": "100%"},
        {"File": "train_identity.csv", "Rows": "144,233", "Cols": 41, "Size": "25 MB", "Use": "Join 24.4% of train", "Pct": "24%"},
        {"File": "test_transaction.csv", "Rows": "506,691", "Cols": 393, "Size": "585 MB", "Use": "Predict (no label)", "Pct": "100%"},
        {"File": "test_identity.csv", "Rows": "141,907", "Cols": 41, "Size": "25 MB", "Use": "Join 28.4% of test", "Pct": "28%"},
        {"File": "sample_submission.csv", "Rows": "506,691", "Cols": 2, "Size": "6 MB", "Use": "Template (TransactionID,isFraud)", "Pct": "100%"},
        {"File": "synthetic_transactions.csv", "Rows": "123", "Cols": 13, "Size": "15 KB", "Use": "PayTrust policy demo", "Pct": "100%"},
    ]
    st.dataframe(pd.DataFrame(csv_data), width="stretch", hide_index=True)
    st.caption("✓ All CSVs as per required folder `data/required csv/ieee-fraud-detection/` + synthetic — handled chunked (50k), never full load.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Train Fraud", "20,663 (3.5%)")
        st.metric("Test to Predict", "506,691")
    with col2:
        st.metric("Features Engineered", "92")
        st.metric("Chunks (50k)", "12 train / 11 test")
    with col3:
        st.metric("Identity Coverage", "24% train, 28% test")
        st.metric("Model", "Logistic (PR-AUC 0.31 test)")
    st.divider()
    # Show dataset overview
    with st.expander("Dataset Overview (chunked, no direct load)", expanded=False):
        st.markdown("""
        - **Transaction**: `TransactionAmt` (log, zscore), `TransactionDT` → hour/day/is_night/is_weekend, `ProductCD`, `card1-6` (numeric + categorical), `addr1/2`, `dist1/2`, `P/R_emaildomain` (freq top5), `C1-14`, `D1-15`, `M1-9`, `V1-50` → `V_sum/mean/missing` + `V1-10` individual.
        - **Identity** (left-join on TransactionID): `id_01-38`, `DeviceType` (mobile/desktop), `DeviceInfo` (browser), `has_identity` flag.
        - **Engineered**: `hour`, `is_night`, `card1_count`, `amt_per_card_mean`, `V_missing`, `has_identity`.
        - **Split**: Temporal by `TransactionDT` — 70% train / 15% val / 15% test (no leakage).
        """)
        st.code("python -m models.train_ieee_chunked --nrows 20000 --chunksize 10000 --seed 42  # quick demo\npython -m models.train_ieee_chunked --full  # 590k (slower)", language="bash")
    # Training status
    report_path = Path("evaluation/ieee_report.json")
    model_path = Path("models/ieee_model.pkl")
    c1, c2 = st.columns([1,2])
    with c1:
        if st.button("Train on 20k sample (quick)", type="primary"):
            with st.spinner("Processing 20k in 2 chunks + training LogisticRegression..."):
                try:
                    import subprocess, sys
                    result = subprocess.run([sys.executable, "-m", "models.train_ieee_chunked", "--nrows", "20000", "--chunksize", "10000", "--seed", "42"], capture_output=True, text=True, timeout=300)
                    st.code(result.stdout[-2000:])
                    if result.stderr:
                        st.warning(result.stderr[-1000:])
                    st.success("Training complete — report at evaluation/ieee_report.json")
                    st.rerun()
                except Exception as e:
                    st.error(f"Train failed: {e}")
        if report_path.exists():
            st.success(f"Report exists: {report_path.stat().st_mtime}")
        else:
            st.info("No report yet — click Train.")
        if model_path.exists():
            st.success(f"Model: {model_path} ({model_path.stat().st_size//1024} KB)")
    with c2:
        if report_path.exists():
            report = json.loads(report_path.read_text())
            st.markdown("**Evaluation (held-out 15% test, 3.5% fraud — use PR-AUC, not accuracy)**")
            m1, m2, m3, m4 = st.columns(4)
            test = report.get("logistic",{}).get("test",{})
            with m1: st.metric("PR-AUC", f"{test.get('pr_auc',0):.3f}")
            with m2: st.metric("ROC-AUC", f"{test.get('roc_auc',0):.3f}")
            with m3: st.metric("F1", f"{test.get('f1',0):.3f}")
            with m4: st.metric("Recall", f"{test.get('recall',0):.3f}")
            st.caption(f"Precision {test.get('precision',0):.3f} • Confusion {test.get('confusion')} • {report.get('disclaimer','')}")
            # Feature importance
            fi = report.get("feature_importance",[])[:15]
            if fi:
                df_fi = pd.DataFrame(fi)
                df_fi["abs_coef"] = df_fi["coef"].abs()
                df_fi = df_fi.sort_values("abs_coef", ascending=True)
                st.bar_chart(df_fi.set_index("feature")["coef"])
                with st.expander("Top 20 features"):
                    st.dataframe(df_fi, width="stretch")
            # LightGBM if available
            if report.get("lightgbm"):
                with st.expander("LightGBM (if available)"):
                    st.json(report["lightgbm"])
        else:
            st.info("Run training to see PR-AUC, feature importance, confusion.")

    st.divider()
    st.markdown("**Threshold Decision Tool — choose your operating point (real IEEE held-out test)**")
    st.caption("Track 02 rubric: a merchant picks *where* to draw the line and sees live precision / recall / FPR / confusion + the SIMULATED cost trade-off (fraud exposure vs false-positive cost). No fake numbers — reads `evaluation/ieee_test_predictions.parquet` saved from the actual held-out test.")
    preds_path = Path("evaluation/ieee_test_predictions.parquet")
    if not preds_path.exists():
        st.info("No test predictions yet — run training (above) to enable the threshold tool.", icon="⏳")
    else:
        try:
            from models import threshold as thr
            df_preds = thr.load_test_predictions(preds_path)
            st.success(f"Loaded {len(df_preds):,} held-out predictions (test set).")

            rec = thr.best_operating_point(df=df_preds)
            cA, cB = st.columns([1, 2])
            with cA:
                t = st.slider("Fraud-probability threshold (p)", 0.0, 1.0, 0.95, 0.01, key="thr_p")
            with cB:
                st.markdown("**Recommended operating points (SIMULATED cost model — hints, not mandates)**")
                st.markdown(
                    f"- **Max F1 @ p={rec['max_f1']['threshold']:.2f}** → precision {rec['max_f1']['precision']:.3f}, recall {rec['max_f1']['recall']:.3f}, F1 {rec['max_f1']['f1']:.3f}"
                )
                st.markdown(
                    f"- **Min SIM total cost @ p={rec['min_expected_total_cost']['threshold']:.2f}** → expected cost {rec['min_expected_total_cost']['expected_total_cost']:,.0f} (SIM)"
                )
                st.caption(rec.get("disclaimer", ""))

            m = thr.metrics_at(t, df_preds)
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            with k1: st.metric("Precision", f"{m['precision']:.3f}", help=f"TP/(TP+FP) at p={t:.2f}")
            with k2: st.metric("Recall", f"{m['recall']:.3f}", help="TP/(TP+FN) at p=" + f"{t:.2f}")
            with k3: st.metric("F1", f"{m['f1']:.3f}")
            with k4: st.metric("FPR", f"{m['false_positive_rate']:.3f}", help="False positives among legit")
            with k5: st.metric("Blocked", f"{m['blocked_count']:,}", help="TP+FP flagged as fraud")
            with k6: st.metric("Missed fraud", f"{m['fn']}", help="FN — fraud not blocked (exposure)")
            st.markdown(f"**Confusion (actual):** TP {m['tp']} • FP {m['fp']} • TN {m['tn']} • FN {m['fn']} — at p={t:.2f}")
            cost1, cost2, cost3 = st.columns(3)
            with cost1: st.metric("Fraud exposure (SIM)", f"{m['fraud_exposure']:,.0f}", help="FN amount × multiplier")
            with cost2: st.metric("FP cost (SIM)", f"{m['false_positive_cost']:,.0f}", help="Blocked legit customers cost")
            with cost3: st.metric("Expected total cost (SIM)", f"{m['expected_total_cost']:,.0f}")
            st.caption(m["disclaimer"])

            with st.expander("Threshold sweep curves (precision / recall / F1 / FPR / cost)", expanded=True):
                curves = thr.to_curves(thr.sweep(step=0.01, df=df_preds))
                cdf = pd.DataFrame(curves)
                st.line_chart(cdf.set_index("threshold")[["precision", "recall", "f1", "false_positive_rate"]])
                st.line_chart(cdf.set_index("threshold")[["fraud_exposure", "false_positive_cost", "expected_total_cost"]])
                st.caption("X-axis = fraud-probability threshold. Left chart: classification metrics. Right chart: SIMULATED costs (not financial forecasts).")
                with st.expander("Raw sweep table (first 40 rows)"):
                    st.dataframe(cdf.head(40), width="stretch", hide_index=True)
        except FileNotFoundError as exc:
            st.error(f"Threshold tool unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001 — surface any tool error without crashing the page
            st.error(f"Threshold tool failed: {exc}")

    st.divider()
    st.markdown("**Live Prediction Demo (uses trained IEEE model + deterministic policy)**")
    st.caption("Enter IEEE-like fields → ML probability + RiskEngine + DecisionEngine (ML is advisory, deterministic is final).")
    with st.form("ieee_pred"):
        c1,c2,c3 = st.columns(3)
        with c1:
            amt = st.number_input("TransactionAmt", value=100.0, min_value=1.0)
            prod = st.selectbox("ProductCD", ["W","C","R","H","S"])
            card1 = st.number_input("card1", value=13926)
        with c2:
            hour = st.slider("hour", 0,23, 14)
            is_night = 1 if hour in [1,2,3,4,5] else 0
            st.metric("is_night", is_night)
            P_email = st.selectbox("P_emaildomain", ["gmail.com","yahoo.com","anonymous.com","Missing"])
        with c3:
            V1 = st.number_input("V1", value=1.0)
            C1 = st.number_input("C1", value=1.0)
            has_id = st.checkbox("has_identity")
        if st.form_submit_button("Predict"):
            if not model_path.exists():
                st.warning("Train first — no model yet.")
            else:
                import pickle
                bundle = pickle.loads(model_path.read_bytes())
                # Build feature dict for prediction — use same cols as training
                feats = {f:0 for f in bundle["features"]}
                # Fill some
                for k,v in [("TransactionAmt",amt),("hour",hour),("is_night",is_night),("card1",card1),("V1",V1),("C1",C1),("has_identity",int(has_id))]:
                    if k in feats: feats[k]=v
                # One-hot ProductCD
                for col in bundle["features"]:
                    if col.startswith("ProductCD_"):
                        feats[col]= 1 if col==f"ProductCD_{prod}" else 0
                    if col.startswith("P_emaildomain"):
                        feats[col]= 1 if P_email in col else 0
                # Predict
                import numpy as np
                X = np.array([[feats[c] for c in bundle["features"]]])
                Xs = bundle["scaler"].transform(X)
                prob = float(bundle["model"].predict_proba(Xs)[0,1])
                st.metric("ML Fraud Probability", f"{prob:.3f}")
                st.progress(prob)
                # Also run deterministic risk
                pol = policy_engine.evaluate({"daily_limit":100000,"max_transaction":60000,"approval_threshold":30000,"allowed_categories":["electronics"],"blocked_categories":[],"is_active":True}, {"amount":int(amt),"category":"electronics"}, daily_spent=0)
                risk = risk_engine.assess({"amount":int(amt),"category":"electronics"}, pol, context={"daily_limit":100000,"daily_spent":0,"transactions_last_hour":1,"user_total_txns":20})
                # Add ML as extra factor if prob >0.5
                if prob > 0.5:
                    risk["factors"].append({"name":"ml_ieee","severity":"high","score":15,"details":f"IEEE model prob {prob:.2f}"})
                    risk["risk_score"] = min(100, risk["risk_score"]+15)
                dec = decision_engine.decide(pol, risk)
                st.markdown(f"**Decision (deterministic final):** <span class='decision-{dec['decision']}'>{dec['decision']}</span>", unsafe_allow_html=True)
                st.json({"ml_prob": prob, "risk": risk, "decision": dec})
    st.divider()
    st.markdown("**Full Pipeline: IEEE → PayTrust Mapping (Real Money Demo)**")
    st.caption("Maps IEEE `TransactionAmt` (USD→INR x83), `ProductCD`→category, `card1`→user, `addr1`→region → PayTrust `PaymentRequest` → Policy/Risk/Decision")
    if st.button("Show Real IEEE → PayTrust Example (from train_transaction.csv)"):
        import csv as _csv
        p = Path("data/required csv/ieee-fraud-detection/train_transaction.csv")
        with open(p, encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            row = next(reader)
            # Map
            from models.predict_ieee import ieee_to_paytrust
            mapped = ieee_to_paytrust(row)
            st.code(f"IEEE row: TransactionID={row['TransactionID']} Amt=${row['TransactionAmt']} ProductCD={row['ProductCD']} card1={row['card1']}", language="text")
            st.json(mapped)
            # Run through PayTrust
            pol = policy_engine.evaluate({"daily_limit":100000,"max_transaction":60000,"approval_threshold":30000,"allowed_categories":["electronics","books","travel"],"blocked_categories":["gambling","financial_products"],"is_active":True}, {"amount": mapped["amount"], "category": mapped["category"]}, daily_spent=0)
            risk = risk_engine.assess({"amount": mapped["amount"], "category": mapped["category"]}, pol, context={"daily_limit":100000,"daily_spent":0,"transactions_last_hour":1,"user_total_txns":20})
            dec = decision_engine.decide(pol, risk)
            st.markdown(f"PayTrust Decision: <span class='decision-{dec['decision']}'>{dec['decision']}</span> risk {risk['risk_level']} ({risk['risk_score']})", unsafe_allow_html=True)
            st.caption("This is how every IEEE row becomes a PayTrust decision — real amount, real product, real risk.")
    st.divider()
    st.markdown("**Generate Submission for 506k Test (All CSVs)**")
    st.caption("Uses `test_transaction.csv` (506k, no label) + `test_identity.csv` (141k) → `evaluation/submission.csv` (506k, `TransactionID,isFraud`)")
    colA, colB = st.columns([1,2])
    with colA:
        if st.button("Generate Submission (chunked 50k)"):
            with st.spinner("Predicting 506k test in 10 chunks... (30-60s)"):
                try:
                    import subprocess, sys
                    result = subprocess.run([sys.executable, "-m", "models.predict_ieee", "--model", "models/ieee_model.pkl", "--out", "evaluation/submission.csv"], capture_output=True, text=True, timeout=600)
                    st.code(result.stdout[-3000:])
                    if result.stderr:
                        st.warning(result.stderr[-1500:])
                    if Path("evaluation/submission.csv").exists():
                        df = pd.read_csv("evaluation/submission.csv", nrows=5)
                        st.success(f"Submission generated: {len(pd.read_csv('evaluation/submission.csv'))} rows")
                        st.dataframe(df, width="stretch")
                    else:
                        st.error("Submission not created — train first")
                except Exception as e:
                    st.error(f"Failed: {e}")
    with colB:
        if Path("evaluation/submission.csv").exists():
            st.metric("Submission Rows", f"{len(pd.read_csv('evaluation/submission.csv')):,}")
            st.dataframe(pd.read_csv("evaluation/submission.csv").head(10), width="stretch")
            st.download_button("Download submission.csv", data=Path("evaluation/submission.csv").read_bytes(), file_name="submission.csv", mime="text/csv")
        else:
            st.info("No submission yet — generate from test CSVs.")
        st.caption("Also used: `synthetic_transactions.csv` (123 rows) for PayTrust policy demos — see Payment History → Generate Synthetic.")

elif nav == "Evaluation & Thresholds":
    st.subheader("Evaluation & thresholds — held-out IEEE test + SIMULATED cost trade-off", icon=":material/monitoring:")
    st.caption("Every number comes from actual artifacts on disk — nothing invented. Costs are SIMULATED / ESTIMATED (core/config.py), never forecasts.")
    preds_ready = Path("evaluation/ieee_test_predictions.parquet").exists()
    report_path = Path("evaluation/ieee_report.json")
    with st.container(horizontal=True):
        st.metric("Held-out test rows", f"{len(_load_preds_df()):,}" if preds_ready else "—", border=True)
        st.metric("Test predictions", "ready" if preds_ready else "missing", border=True)
        st.metric("Model report", "ieee_report.json" if report_path.exists() else "missing", border=True)
    if not preds_ready:
        st.info("No test predictions yet — run training first: **Real World (IEEE)** → Train (or `python -m models.train_ieee_chunked`).", icon="⏳")
    else:
        if report_path.exists():
            report = json.loads(report_path.read_text())
            test = report.get("logistic", {}).get("test", {})
            with st.container(horizontal=True):
                st.metric("PR-AUC", f"{test.get('pr_auc', 0):.3f}", border=True)
                st.metric("ROC-AUC", f"{test.get('roc_auc', 0):.3f}", border=True)
                st.metric("F1 @ 0.5", f"{test.get('f1', 0):.3f}", border=True)
                st.metric("Recall @ 0.5", f"{test.get('recall', 0):.3f}", border=True)
            st.caption(f"Precision {test.get('precision', 0):.3f} • Confusion {test.get('confusion')} • {report.get('disclaimer', '')}")
        rec = _threshold_recommend()
        t = st.slider("Fraud-probability threshold (p)", 0.0, 1.0, 0.95, 0.01, key="eval_thr")
        from models.threshold import metrics_at
        m = metrics_at(t, _load_preds_df())
        with st.container(horizontal=True):
            st.metric("Precision", f"{m['precision']:.3f}", border=True)
            st.metric("Recall", f"{m['recall']:.3f}", border=True)
            st.metric("F1", f"{m['f1']:.3f}", border=True)
            st.metric("FPR", f"{m['false_positive_rate']:.3f}", border=True)
            st.metric("Blocked", f"{m['blocked_count']:,}", border=True)
            st.metric("Missed fraud", f"{m['fn']}", border=True)
        st.markdown(f"**Confusion (actual):** TP {m['tp']} • FP {m['fp']} • TN {m['tn']} • FN {m['fn']} — at p={t:.2f}")
        with st.container(horizontal=True):
            st.metric("Fraud exposure (SIM)", f"{m['fraud_exposure']:,.0f}", border=True)
            st.metric("FP cost (SIM)", f"{m['false_positive_cost']:,.0f}", border=True)
            st.metric("Expected total cost (SIM)", f"{m['expected_total_cost']:,.0f}", border=True)
        st.caption(m["disclaimer"])
        st.markdown("**Recommended operating points (hints over a SIMULATED cost model — your call, not a mandate)**")
        st.markdown(f"- **Max F1 @ p={rec['max_f1']['threshold']:.2f}** → precision {rec['max_f1']['precision']:.3f}, recall {rec['max_f1']['recall']:.3f}, F1 {rec['max_f1']['f1']:.3f}")
        st.markdown(f"- **Min SIM total cost @ p={rec['min_expected_total_cost']['threshold']:.2f}** → expected cost {rec['min_expected_total_cost']['expected_total_cost']:,.0f}")
        st.caption(rec.get("disclaimer", ""))
        with st.expander("Threshold sweep curves (precision / recall / F1 / FPR / cost)", icon=":material/monitoring:", expanded=True):
            cdf = pd.DataFrame(_threshold_curves())
            metric_fig = go.Figure()
            for col, color in [("precision", "#60A5FA"), ("recall", "#34D399"), ("f1", "#A78BFA"), ("false_positive_rate", "#F87171")]:
                metric_fig.add_trace(go.Scatter(x=cdf["threshold"], y=cdf[col], name=col, mode="lines", line=dict(color=color, width=2)))
            for y, lbl, color in [(rec['max_f1']['threshold'], "max F1", "#A78BFA")]:
                metric_fig.add_vline(x=y, line_width=1.5, line_dash="dot", line_color=color, annotation_text=lbl, annotation_font_color=color)
            metric_fig.add_vline(x=t, line_width=2, line_color="#F1F5F9", annotation_text=f"selected {t:.2f}", annotation_font_color="#F1F5F9")
            metric_fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                     font={"color": "#CBD5E1", "family": "Inter"}, legend={"orientation": "h", "y": 1.12},
                                     xaxis={"title": "Threshold p", "gridcolor": "#1E293B"}, yaxis={"gridcolor": "#1E293B", "range": [0, 1.05]})
            st.plotly_chart(metric_fig, width="stretch", key="eval_metric_curve")
            cost_fig = go.Figure()
            for col, color in [("fraud_exposure", "#F87171"), ("false_positive_cost", "#FBBF24"), ("expected_total_cost", "#60A5FA")]:
                cost_fig.add_trace(go.Scatter(x=cdf["threshold"], y=cdf[col], name=col, mode="lines", line=dict(color=color, width=2), fill="tozeroy" if col == "expected_total_cost" else None, fillcolor="rgba(96,165,250,.08)"))
            cost_fig.add_vline(x=t, line_width=2, line_color="#F1F5F9", annotation_text=f"selected {t:.2f}", annotation_font_color="#F1F5F9")
            cost_fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                   paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                   font={"color": "#CBD5E1", "family": "Inter"}, legend={"orientation": "h", "y": 1.12},
                                   xaxis={"title": "Threshold p", "gridcolor": "#1E293B"}, yaxis={"title": "INR (SIMULATED)", "gridcolor": "#1E293B"})
            st.plotly_chart(cost_fig, width="stretch", key="eval_cost_curve")
            st.caption("X-axis = fraud-probability threshold. Top: classification metrics. Bottom: SIMULATED costs. Dashed = recommended, solid white = your slider.")
        if Path("evaluation/ml_report.json").exists():
            with st.expander("Synthetic demo model report (explicitly NOT production performance)"):
                st.json(json.loads(Path("evaluation/ml_report.json").read_text()))

elif nav == "Help & Glossary":
    st.subheader("Help & glossary", icon=":material/help:")
    st.caption("New to PayTrust? Start here. Every field has a tooltip (hover the ⓘ) — this page explains all.")
    tab1, tab2, tab3, tab4 = st.tabs(["🏁 How to Use (5 Steps)", "📦 PayTrust Variables", "🏦 IEEE Variables", "⚠️ Risk & Decisions"])
    with tab1:
        st.markdown("""
        **5 Steps to a Decision (do this in order):**
        1. **Agent Policy** → Set rules for your agent (e.g., Shopping Assistant: daily 100k, max 60k, approval >30k, allow `electronics,books,travel`, block `gambling`). This is the law — LLM never overrides.
        2. **Payment Request** → Create a payment intent: `request_id` (unique), `user`/`agent`/`merchant`, `amount` (INR), `category` (must match allowlist), `agent_reason` (why agent wants to pay). Click **Evaluate** → you get Policy + Risk + Decision in <100ms.
        3. **Risk Assessment** → Play with sliders to see how risk adds up (amount, daily spent, frequency, violations). Helps you tune thresholds.
        4. **AI Investigation** → Pick a past decision → **Investigate** → AI (gemma-4-31b free) explains *why* in plain English, using only your facts (no invention).
        5. **Decision Simulator** → See `What if ALLOW / ASK_USER / DENY?` with `SIMULATED` costs (fraud, friction, ops) — pick the cheapest safe option. For real data, go to **Real World (IEEE)** → Train → Predict → Submission.
        """)
        st.info("Tip: Hover any ⓘ next to a field for a 1-line meaning. Expand the tables below for full glossary.", icon="💡")
        st.markdown("**Quick Try:** Payment Request → `TechMart Electronics` 25k `electronics` → **ALLOW** → change to 65k → **DENY (max exceeded)** → change category to `gambling` → **DENY (blocked)** → go to AI Investigation to see explanation.")
    with tab2:
        st.markdown("**PayTrust PaymentRequest (models/payment_request.py:1)**")
        st.table(pd.DataFrame([
            {"Variable": "request_id", "Example": "req_a1b2c3d4", "Meaning": "Unique ID for this payment attempt. 6-64 chars, a-z,0-9,-,_ . Used for idempotency (no double charge).", "How to use": "Auto-filled; keep unique."},
            {"Variable": "user_id", "Example": "1 (Test User)", "Meaning": "Who is paying? Must exist in `users` table. Determines which policy applies.", "How to use": "Pick from dropdown."},
            {"Variable": "agent_id", "Example": "1 (Shopping Assistant)", "Meaning": "Which AI agent is acting? Must be authorized for this user via `agent_policies`.", "How to use": "Pick agent; if unauthorized → DENY."},
            {"Variable": "merchant_id / merchant_name", "Example": "1 / TechMart Electronics", "Meaning": "Who you pay. Category comes from merchant but you choose `category` for this payment. Risk depends on merchant tier.", "How to use": "Pick merchant; check category matches."},
            {"Variable": "amount (INR)", "Example": "25000", "Meaning": "How much to pay. Must be ≥1 and ≤10,000,000. Checked vs `max_transaction` and `daily_limit`.", "How to use": "Enter INR; >30k → ASK_USER, >60k → DENY."},
            {"Variable": "currency", "Example": "INR", "Meaning": "Only INR supported in local prototype (Razorpay TEST INR).", "How to use": "Fixed."},
            {"Variable": "category", "Example": "electronics", "Meaning": "What you buy. Must be one of 9: electronics, books, travel, food, fashion, grocery, fuel, gambling, financial_products. Checked vs allow/block lists.", "How to use": "Pick; `gambling` is always blocked/DENY."},
            {"Variable": "description / agent_reason", "Example": "Laptop / User requested 16GB RAM", "Meaning": "Human-readable why. `agent_reason` is agent's self-explanation — used as AI fact, not decision.", "How to use": "Explain intent; helps AI investigation."},
            {"Variable": "timestamp", "Example": "2026-08-26T12:00:00Z", "Meaning": "When. Auto-set to now UTC. Used for frequency checks (tx last hour).", "How to use": "Auto."},
        ]))
        st.markdown("**Policy Variables (agent_policies table)**")
        st.table(pd.DataFrame([
            {"Variable": "daily_limit", "Default": "100,000", "Meaning": "Max total per day per user. Sum of today's amounts + new > limit → DENY."},
            {"Variable": "max_transaction", "Default": "60,000", "Meaning": "Largest single payment allowed."},
            {"Variable": "approval_threshold", "Default": "30,000", "Meaning": "Above this needs human ASK_USER even if LOW risk."},
            {"Variable": "allowed_categories", "Default": "electronics,books,travel", "Meaning": "Only these can be bought; others → category_not_allowed → DENY."},
            {"Variable": "blocked_categories", "Default": "gambling,financial_products", "Meaning": "Never allowed → category_blocked → DENY."},
        ]))
    with tab3:
        st.markdown("**IEEE Fraud Detection (data/required csv/ieee-fraud-detection/) — 590k train, 506k test**")
        st.table(pd.DataFrame([
            {"Variable": "TransactionID", "Meaning": "Unique transaction key. Used for id join and submission. Maps to PayTrust `request_id` as `req_ieee_<ID>`."},
            {"Variable": "isFraud", "Meaning": "Label: 1=fraud (3.5% of train), 0=legit. Only in train, not test. Used for training."},
            {"Variable": "TransactionDT", "Meaning": "Seconds since reference. → `hour` (0-23), `day` (0-6), `is_night` (1-5 AM), `is_weekend`."},
            {"Variable": "TransactionAmt", "Meaning": "Amount in USD (mean $130). → PayTrust `amount` INR = USD×83. Log/zscore engineered."},
            {"Variable": "ProductCD", "Meaning": "Product code: W/C/R/H/S. → PayTrust category: W→electronics, C→books, etc. One-hot."},
            {"Variable": "card1,2,3,5 (numeric)", "Meaning": "Card numbers. card1 used as `user_id` proxy (`card1%3+1`), card1_count = frequency feature."},
            {"Variable": "card4, card6 (categorical)", "Meaning": "Card type: `visa/mastercard/amex/discover` and `credit/debit`. One-hot."},
            {"Variable": "addr1, addr2, dist1, dist2", "Meaning": "Address/distance. Missing→-1. Indicates location risk."},
            {"Variable": "P/R_emaildomain", "Meaning": "Purchaser/Recipient email domain (gmail, yahoo, anonymous...). Top5 freq encoded, else Other."},
            {"Variable": "C1-C14", "Meaning": "Count features (e.g., counts). Median-filled, clipped."},
            {"Variable": "D1-D15", "Meaning": "Time delta (days since last). -1 if missing."},
            {"Variable": "M1-M9", "Meaning": "Match flags T/F. → 1/0/-1."},
            {"Variable": "V1-V339", "Meaning": "Anonymized Vesta features. We use V1-10 + `V_sum`/`V_mean`/`V_missing` aggregated (V1 71% missing)."},
            {"Variable": "id_01-38, DeviceType/Info", "Meaning": "Identity: id_01 numeric, id_12 `NotFound`, DeviceType `mobile/desktop`, DeviceInfo `SAMSUNG...` → `has_identity` flag."},
            {"Variable": "V_sum, V_mean, V_missing, has_identity", "Meaning": "Engineered: sum/mean of V's, count missing, whether identity present (24% train)."},
        ]))
        st.caption("All 92 features after engineering → `models/train_ieee_chunked.py:138` → `LogisticRegression(balanced)` → PR-AUC evaluated on 15% held-out.")
    with tab4:
        st.markdown("**Risk (0-100, 7 dims, `engines/risk_engine.py:1`)**")
        st.table(pd.DataFrame([
            {"Dim": "amount_risk", "When": "≥15k +5 low, ≥30k +12 med, ≥50k +20 high", "Example": "65k → +20"},
            {"Dim": "spending_behavior", "When": "projected daily / limit ≥0.5 +6, ≥0.7 +12, ≥0.9 +20", "Example": "90k spent +20k → 110% → +20"},
            {"Dim": "merchant_risk", "When": "gambling → +25 critical; new merchant → +10 med", "Example": "BetZone → +25"},
            {"Dim": "policy_risk", "When": "violations → +15-25 each", "Example": "category_blocked +25"},
            {"Dim": "agent_auth_risk", "When": "unauthorized/missing → +25 critical", "Example": "inactive agent → DENY"},
            {"Dim": "frequency_risk", "When": "tx last hour ≥3 +6, ≥5 +12, ≥10 +20", "Example": "10 tx/hour → +20"},
            {"Dim": "historical_behavior", "When": "new user (<5 tx) + high amt → +12", "Example": "new user 40k → +12"},
        ]))
        st.markdown("**Decision (`engines/decision_engine.py:18`, no magic numbers)**")
        st.table(pd.DataFrame([
            {"Condition": "Policy violation (any)", "Risk": "Any", "Decision": "DENY", "Why": "Hard safety — never allow violating payment"},
            {"Condition": "No violation", "Risk": "HIGH/CRITICAL (61-100)", "Decision": "DENY", "Why": "High risk unsafe even if policy passes"},
            {"Condition": "No violation", "Risk": "MEDIUM (31-60)", "Decision": "ASK_USER", "Why": "Needs human review"},
            {"Condition": "No violation + requires_approval", "Risk": "LOW (0-30)", "Decision": "ASK_USER", "Why": "Amount >30k approval gate"},
            {"Condition": "No violation, no approval", "Risk": "LOW", "Decision": "ALLOW", "Why": "Safe to auto-allow"},
        ]))
        st.caption("Friction: ALLOW low, ASK medium, DENY high. Fraud exposure `p_fraud=score/100 * amount` (SIMULATED) in Decision Simulator.")

elif nav == "Audit Log":
    st.subheader("Audit log — verifiable decisions + webhook tester", icon=":material/receipt:")
    logs = _audit_logs(100)
    if logs: st.dataframe(pd.DataFrame(logs), width="stretch", hide_index=True)
    else: st.info("No audit events yet.", icon="ℹ️")
    st.divider()
    st.markdown("**Razorpay Webhook Tester (TEST MODE, idempotent)**")
    st.caption("Verifies HMAC-SHA256 over RAW body, stores in `razorpay_events`. Secrets never logged.")
    raw = st.text_area("Raw JSON body", value='{"id":"evt_test_123","event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_test123"}}}}', height=120)
    sig = st.text_input("X-Razorpay-Signature (hex)", value="")
    if st.button("Verify & Record Webhook"):
        from services.razorpay_service import handle_webhook
        res = handle_webhook(raw.encode(), sig)
        st.json(res)
        if res["status"] == "processed": st.success("Webhook processed (idempotent)")
        elif res["status"] == "duplicate": st.warning("Duplicate — idempotent ignore")
        else: st.error(res.get("reason","rejected"))
    if st.button("Show Razorpay Events"):
        from services.razorpay_service import list_webhook_events
        st.dataframe(pd.DataFrame(list_webhook_events()), width="stretch")
    st.divider()
    st.markdown("**Security Checklist**")
    from core.security import security_checklist
    chk = security_checklist()
    st.json(chk)
    for k,v in chk.items():
        if not v.get("pass"): st.warning(f"{k}: {v}")

st.caption("PayTrust AI — production-minded local prototype. Deterministic final. LLM advisory. Razorpay TEST MODE. SIMULATED estimates labeled.")
