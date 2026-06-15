import os
import logging

# ── CRITICAL: load .env BEFORE importing any app modules ─────────────────────
# app.sheets / app.ai_parser / app.whatsapp all read os.getenv() at call-time,
# but FastAPI startup hooks fire early — keep load_dotenv() here at the top.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, HTMLResponse

from app.whatsapp import send_whatsapp_message
from app.ai_parser import parse_lead_from_message
from app.sheets import append_lead_to_sheet, setup_sheet_headers, get_all_leads

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Lead CRM")

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_secure_token")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("Running startup: setting up sheet headers...")
    await setup_sheet_headers()


# ── Webhook verification (Meta requires this on setup) ────────────────────────
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Main webhook receiver ─────────────────────────────────────────────────────
@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    logger.info(f"Incoming webhook: {body}")

    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_message"}

        message = messages[0]
        msg_type = message.get("type")

        # Only handle text messages
        if msg_type != "text":
            return {"status": "ignored", "reason": f"type={msg_type}"}

        sender_phone = message["from"]
        text = message["text"]["body"]
        msg_id = message["id"]
        timestamp = message.get("timestamp")

        # Get sender's display name if available
        contacts = value.get("contacts", [{}])
        sender_name = contacts[0].get("profile", {}).get("name", "Unknown") if contacts else "Unknown"

        logger.info(f"Message from {sender_name} ({sender_phone}): {text}")

        # Parse with Gemini AI
        lead_data = await parse_lead_from_message(
            text=text,
            sender_phone=sender_phone,
            sender_name=sender_name,
            timestamp=timestamp,
        )

        # Save to Google Sheet
        await append_lead_to_sheet(lead_data)

        # Reply to user
        reply = (
            f"Hi {lead_data['name']}! 👋 Thanks for reaching out.\n\n"
            f"We've captured your enquiry about *{lead_data['topic']}* "
            f"and our team will get back to you shortly!"
        )
        await send_whatsapp_message(to=sender_phone, text=reply)

        return {"status": "ok", "lead": lead_data}

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {"status": "WhatsApp Lead CRM is running 🚀"}


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    leads = await get_all_leads()

    wa_number = os.getenv("WHATSAPP_DISPLAY_NUMBER", "")
    wa_link = os.getenv("WHATSAPP_DEEP_LINK", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else "#"

    # ── Stats ────────────────────────────────────────────────────────────────
    total = len(leads)
    high_urgency = sum(1 for l in leads if l.get("urgency", "").lower() == "high")
    new_leads = sum(1 for l in leads if l.get("status", "").lower() == "new")

    intent_counts: dict = {}
    for l in leads:
        k = l.get("intent", "other").capitalize()
        intent_counts[k] = intent_counts.get(k, 0) + 1

    # ── Build table rows ─────────────────────────────────────────────────────
    def urgency_badge(u: str) -> str:
        color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(u.lower(), "#6b7280")
        return f'<span class="badge" style="background:{color}20;color:{color};border:1px solid {color}40">{u.capitalize()}</span>'

    def intent_badge(i: str) -> str:
        colors = {
            "purchase": "#8b5cf6", "inquiry": "#3b82f6", "support": "#f59e0b",
            "complaint": "#ef4444", "partnership": "#10b981", "other": "#6b7280",
        }
        c = colors.get(i.lower(), "#6b7280")
        return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{i.capitalize()}</span>'

    rows_html = ""
    if not leads:
        rows_html = '<tr><td colspan="8" class="empty-row">No leads yet — send a WhatsApp message to get started! 🚀</td></tr>'
    else:
        for lead in reversed(leads):   # newest first
            rows_html += f"""
            <tr>
                <td class="td-time">{lead.get('timestamp','—')}</td>
                <td class="td-name">{lead.get('name','—')}</td>
                <td class="td-phone">{lead.get('phone','—')}</td>
                <td>{lead.get('topic','—')}</td>
                <td>{intent_badge(lead.get('intent','other'))}</td>
                <td>{urgency_badge(lead.get('urgency','low'))}</td>
                <td class="td-summary">{lead.get('summary','—')}</td>
                <td>{lead.get('status','—')}</td>
            </tr>"""

    # ── Intent distribution bars ─────────────────────────────────────────────
    intent_bars = ""
    for label, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
        pct = int((count / total * 100)) if total else 0
        intent_bars += f"""
        <div class="bar-row">
            <span class="bar-label">{label}</span>
            <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
            <span class="bar-count">{count}</span>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>WhatsApp Lead CRM — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:        #0a0f1e;
    --surface:   #111827;
    --surface2:  #1a2235;
    --border:    #1f2d45;
    --accent:    #25d366;
    --accent2:   #128c7e;
    --text:      #e2e8f0;
    --muted:     #64748b;
    --radius:    14px;
    --shadow:    0 4px 24px rgba(0,0,0,.45);
  }}

  body {{
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0 0 60px;
  }}

  /* ── Header ── */
  .header {{
    background: linear-gradient(135deg, #0a1628 0%, #0d1f3c 50%, #0f2a1a 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
    backdrop-filter: blur(12px);
  }}
  .header-left {{ display: flex; align-items: center; gap: 14px; }}
  .logo-icon {{
    width: 44px; height: 44px; border-radius: 12px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; box-shadow: 0 0 20px rgba(37,211,102,.3);
  }}
  .header h1 {{ font-size: 1.3rem; font-weight: 700; letter-spacing: -.3px; }}
  .header p {{ font-size: .78rem; color: var(--muted); margin-top: 2px; }}
  .header-actions {{ display: flex; gap: 10px; align-items: center; }}

  .btn {{
    display: inline-flex; align-items: center; gap: 7px;
    padding: 9px 18px; border-radius: 10px; font-size: .82rem;
    font-weight: 600; text-decoration: none; cursor: pointer;
    transition: all .2s ease; border: none;
  }}
  .btn-wa {{
    background: linear-gradient(135deg, #25d366, #128c7e);
    color: #fff;
    box-shadow: 0 4px 14px rgba(37,211,102,.35);
  }}
  .btn-wa:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(37,211,102,.5); }}
  .btn-sheet {{
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
  }}
  .btn-sheet:hover {{ background: var(--border); }}
  .refresh-btn {{
    background: var(--surface2); color: var(--muted);
    border: 1px solid var(--border); font-size: .8rem;
  }}
  .refresh-btn:hover {{ color: var(--text); border-color: var(--accent); }}

  /* ── Main content ── */
  .content {{ max-width: 1400px; margin: 0 auto; padding: 32px 40px 0; }}

  /* ── Stats cards ── */
  .stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px; margin-bottom: 28px;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 22px 24px;
    position: relative; overflow: hidden;
    transition: transform .2s, box-shadow .2s;
  }}
  .stat-card:hover {{ transform: translateY(-3px); box-shadow: var(--shadow); }}
  .stat-card::before {{
    content: ''; position: absolute;
    inset: 0; border-radius: var(--radius);
    background: linear-gradient(135deg, transparent 60%, rgba(37,211,102,.06));
    pointer-events: none;
  }}
  .stat-icon {{ font-size: 2rem; margin-bottom: 12px; }}
  .stat-value {{ font-size: 2.4rem; font-weight: 800; line-height: 1; }}
  .stat-label {{ font-size: .78rem; color: var(--muted); margin-top: 6px; text-transform: uppercase; letter-spacing: .8px; }}
  .stat-card.green .stat-value {{ color: #25d366; }}
  .stat-card.red   .stat-value {{ color: #ef4444; }}
  .stat-card.blue  .stat-value {{ color: #3b82f6; }}
  .stat-card.amber .stat-value {{ color: #f59e0b; }}

  /* ── Two column layout ── */
  .row {{ display: grid; grid-template-columns: 1fr 320px; gap: 20px; margin-bottom: 24px; }}

  /* ── Table card ── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--shadow);
  }}
  .card-header {{
    padding: 18px 24px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    background: var(--surface2);
  }}
  .card-title {{ font-size: .95rem; font-weight: 700; display: flex; align-items: center; gap: 8px; }}
  .card-badge {{
    background: rgba(37,211,102,.15); color: var(--accent);
    font-size: .7rem; font-weight: 700; padding: 2px 8px;
    border-radius: 20px; border: 1px solid rgba(37,211,102,.25);
  }}

  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  th {{
    padding: 11px 14px; text-align: left;
    font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .8px;
    color: var(--muted); background: var(--surface2);
    border-bottom: 1px solid var(--border); white-space: nowrap;
  }}
  td {{
    padding: 13px 14px; border-bottom: 1px solid rgba(31,45,69,.6);
    vertical-align: middle;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(37,211,102,.03); }}

  .td-name  {{ font-weight: 600; }}
  .td-phone {{ font-family: monospace; color: var(--muted); font-size: .78rem; }}
  .td-time  {{ font-size: .75rem; color: var(--muted); white-space: nowrap; }}
  .td-summary {{ color: var(--muted); font-size: .79rem; max-width: 240px;
                  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  .badge {{
    display: inline-block; padding: 3px 9px;
    border-radius: 20px; font-size: .7rem; font-weight: 700;
    white-space: nowrap;
  }}
  .empty-row {{
    text-align: center; padding: 48px; color: var(--muted);
    font-size: .9rem;
  }}

  /* ── Side panel ── */
  .side-panel {{ display: flex; flex-direction: column; gap: 20px; }}

  /* ── Intent bars ── */
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 11px; }}
  .bar-label {{ font-size: .8rem; color: var(--text); min-width: 72px; }}
  .bar-track {{
    flex: 1; height: 6px; background: var(--border);
    border-radius: 99px; overflow: hidden;
  }}
  .bar-fill {{
    height: 100%; border-radius: 99px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width .6s cubic-bezier(.4,0,.2,1);
  }}
  .bar-count {{ font-size: .75rem; color: var(--muted); min-width: 20px; text-align: right; }}

  /* ── Test CTA panel ── */
  .cta-card {{
    background: linear-gradient(135deg, #0d2818 0%, #0a1f2e 100%);
    border: 1px solid rgba(37,211,102,.2);
    border-radius: var(--radius);
    padding: 24px;
    text-align: center;
    box-shadow: 0 0 40px rgba(37,211,102,.08);
  }}
  .cta-card .wa-icon {{ font-size: 3rem; margin-bottom: 12px; }}
  .cta-card h3 {{ font-size: 1rem; font-weight: 700; margin-bottom: 6px; }}
  .cta-card p {{ font-size: .78rem; color: var(--muted); line-height: 1.6; margin-bottom: 16px; }}
  .cta-number {{
    font-size: .85rem; font-family: monospace;
    color: var(--accent); background: rgba(37,211,102,.08);
    padding: 8px 14px; border-radius: 8px; margin-bottom: 16px;
    border: 1px solid rgba(37,211,102,.2); display: block;
  }}
  .btn-wa-large {{
    display: flex; align-items: center; justify-content: center; gap: 8px;
    padding: 13px 20px; border-radius: 11px;
    background: linear-gradient(135deg, #25d366, #128c7e);
    color: #fff; font-weight: 700; font-size: .88rem;
    text-decoration: none;
    box-shadow: 0 6px 20px rgba(37,211,102,.4);
    transition: all .2s;
  }}
  .btn-wa-large:hover {{ transform: translateY(-2px); box-shadow: 0 8px 28px rgba(37,211,102,.55); }}

  /* ── Live dot ── */
  .live-dot {{
    display: inline-block; width: 8px; height: 8px;
    background: #25d366; border-radius: 50%;
    box-shadow: 0 0 8px #25d366;
    animation: pulse 2s infinite;
    margin-right: 6px;
  }}
  @keyframes pulse {{
    0%,100% {{ opacity: 1; transform: scale(1); }}
    50%  {{ opacity: .5; transform: scale(1.4); }}
  }}

  /* ── Responsive ── */
  @media (max-width: 900px) {{
    .row {{ grid-template-columns: 1fr; }}
    .header {{ padding: 16px 20px; flex-wrap: wrap; gap: 12px; }}
    .content {{ padding: 20px 16px 0; }}
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  @media (max-width: 500px) {{
    .stats {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<!-- ── Header ── -->
<header class="header">
  <div class="header-left">
    <div class="logo-icon">💬</div>
    <div>
      <h1>WhatsApp Lead CRM</h1>
      <p><span class="live-dot"></span>Live dashboard · auto-captured via AI</p>
    </div>
  </div>
  <div class="header-actions">
    <a href="/dashboard" class="btn refresh-btn" id="refresh-btn">⟳ Refresh</a>
    <a href="{sheet_url}" target="_blank" class="btn btn-sheet" id="sheet-link">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
      View Sheet
    </a>
    <a href="{wa_link}" target="_blank" class="btn btn-wa" id="wa-header-btn">
      <svg width="15" height="15" viewBox="0 0 32 32" fill="currentColor"><path d="M16 2C8.27 2 2 8.27 2 16c0 2.44.65 4.72 1.77 6.72L2 30l7.48-1.74A13.93 13.93 0 0016 30c7.73 0 14-6.27 14-14S23.73 2 16 2zm0 25.6a11.52 11.52 0 01-5.86-1.6l-.42-.25-4.44 1.03 1.07-4.32-.28-.45A11.56 11.56 0 0116 4.4c6.4 0 11.6 5.2 11.6 11.6S22.4 27.6 16 27.6z"/></svg>
      Test on WhatsApp
    </a>
  </div>
</header>

<!-- ── Main ── -->
<main class="content">

  <!-- Stats -->
  <section class="stats">
    <div class="stat-card green">
      <div class="stat-icon">📥</div>
      <div class="stat-value">{total}</div>
      <div class="stat-label">Total Leads</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-icon">🆕</div>
      <div class="stat-value">{new_leads}</div>
      <div class="stat-label">New Leads</div>
    </div>
    <div class="stat-card red">
      <div class="stat-icon">🔥</div>
      <div class="stat-value">{high_urgency}</div>
      <div class="stat-label">High Urgency</div>
    </div>
    <div class="stat-card amber">
      <div class="stat-icon">🤖</div>
      <div class="stat-value">AI</div>
      <div class="stat-label">Gemini Parsed</div>
    </div>
  </section>

  <!-- Table + Side panel -->
  <div class="row">

    <!-- Leads table -->
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          📋 All Leads
          <span class="card-badge">{total} total</span>
        </span>
        <span style="font-size:.75rem;color:var(--muted)">Newest first</span>
      </div>
      <div class="table-wrap">
        <table id="leads-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Name</th>
              <th>Phone</th>
              <th>Topic</th>
              <th>Intent</th>
              <th>Urgency</th>
              <th>Summary</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Side panel -->
    <aside class="side-panel">

      <!-- Test CTA -->
      <div class="cta-card" id="test-cta">
        <div class="wa-icon">💬</div>
        <h3>Test This Project</h3>
        <p>Send any WhatsApp message to the number below. AI will parse it into a lead and it'll appear in this dashboard instantly.</p>
        <span class="cta-number">{wa_number}</span>
        <a href="{wa_link}" target="_blank" class="btn-wa-large" id="wa-cta-btn">
          <svg width="18" height="18" viewBox="0 0 32 32" fill="currentColor"><path d="M16 2C8.27 2 2 8.27 2 16c0 2.44.65 4.72 1.77 6.72L2 30l7.48-1.74A13.93 13.93 0 0016 30c7.73 0 14-6.27 14-14S23.73 2 16 2zm0 25.6a11.52 11.52 0 01-5.86-1.6l-.42-.25-4.44 1.03 1.07-4.32-.28-.45A11.56 11.56 0 0116 4.4c6.4 0 11.6 5.2 11.6 11.6S22.4 27.6 16 27.6z"/></svg>
          Open in WhatsApp
        </a>
      </div>

      <!-- Intent distribution -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">📊 By Intent</span>
        </div>
        <div style="padding:18px 20px">
          {intent_bars if intent_bars else '<p style="color:var(--muted);font-size:.82rem">No data yet</p>'}
        </div>
      </div>

      <!-- Sheet link panel -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">📄 Google Sheet</span>
        </div>
        <div style="padding:18px 20px;text-align:center">
          <p style="font-size:.78rem;color:var(--muted);margin-bottom:14px;line-height:1.6">
            All leads are also stored in Google Sheets in real-time.
          </p>
          <a href="{sheet_url}" target="_blank" class="btn btn-sheet" style="width:100%;justify-content:center" id="sheet-cta-btn">
            Open Google Sheet ↗
          </a>
        </div>
      </div>

    </aside>
  </div>

</main>

<script>
  // Auto-refresh every 30 seconds
  setTimeout(() => location.reload(), 30000);

  // Animate bar fills on load
  document.querySelectorAll('.bar-fill').forEach(bar => {{
    const w = bar.style.width;
    bar.style.width = '0';
    requestAnimationFrame(() => setTimeout(() => bar.style.width = w, 50));
  }});
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
