#!/usr/bin/env python3
"""
=============================================================================
 DAILY PING SYSTEM — Entry Scanner + Email Alerts
 
 Runs daily via GitHub Actions:
 1. Re-runs entry scanner on top stocks from latest screener results
 2. Compares combined scores against threshold (default: 70)
 3. Sends email alert for any stocks above threshold with:
    - Stock name, ticker, combined/buffett/entry scores
    - Which entry signals triggered
    - Recent price movement context
    - Key fundamentals
 
 USAGE:
   python scripts/daily_ping.py                              # Default settings
   python scripts/daily_ping.py --threshold 70               # Custom threshold
   python scripts/daily_ping.py --dry-run                    # Preview without email
   python scripts/daily_ping.py --force-email                # Send even if no new alerts
   
 ENVIRONMENT VARIABLES (set as GitHub Secrets):
   GMAIL_ADDRESS    — Gmail address to send from
   GMAIL_APP_PW     — Gmail app password (not your regular password)
   ALERT_EMAIL_TO   — Email address to receive alerts
=============================================================================
"""

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def load_previous_alerts() -> set:
    """Load the set of tickers that were alerted yesterday."""
    alert_file = Path("data/previous_alerts.json")
    if alert_file.exists():
        with open(alert_file) as f:
            data = json.load(f)
            return set(data.get("tickers", []))
    return set()


def save_current_alerts(tickers: list[str]):
    """Save today's alerted tickers for tomorrow's comparison."""
    alert_file = Path("data/previous_alerts.json")
    with open(alert_file, "w") as f:
        json.dump({
            "date": datetime.now().isoformat(),
            "tickers": tickers,
        }, f, indent=2)


def build_alert_email(alerts: list[dict], threshold: float) -> tuple[str, str, str]:
    """
    Build the email subject, plain text body, and HTML body.
    Returns (subject, text_body, html_body).
    """
    date_str = datetime.now().strftime("%d %b %Y")
    count = len(alerts)
    
    subject = f"🔔 Oracle's Ledger: {count} stock{'s' if count != 1 else ''} above {threshold:.0f} combined score — {date_str}"
    
    # ── Plain text version ──
    text_lines = [
        f"ORACLE'S LEDGER — Daily Entry Alert",
        f"Date: {date_str}",
        f"Threshold: Combined score > {threshold:.0f}",
        f"Stocks triggered: {count}",
        "",
        "=" * 60,
        "",
    ]
    
    for a in alerts:
        is_new = a.get("is_new", False)
        text_lines.append(f"{'🆕 NEW ' if is_new else ''}{'⬆️ ' if not is_new else ''}{a['ticker']} — {a.get('name', '')}")
        text_lines.append(f"  Combined: {a.get('combined_score', 0):.1f}  |  Buffett: {a.get('buffett_score', 0):.1f}  |  Entry: {a.get('entry_score', 0):.1f}")
        text_lines.append(f"  Price: {a.get('currency', '$')}{a.get('current_price', 0):.2f}  |  Sector: {a.get('sector', 'Unknown')}")
        text_lines.append(f"  P/E: {_fmt(a.get('pe_trailing'))}  |  ROE: {_fmt(a.get('roe'))}%  |  ROIC: {_fmt(a.get('roic'))}%  |  FCF Yield: {_fmt(a.get('fcf_yield'))}%")
        
        # Entry signals
        signals = a.get("entry_signals", [])
        if signals:
            text_lines.append(f"  Signals:")
            for sig in signals:
                text_lines.append(f"    {sig}")
        
        # MA context
        if a.get("ma_200w_distance_pct") is not None:
            text_lines.append(f"  200w MA: {'below' if a.get('ma_200w_below') else 'above'} by {abs(a['ma_200w_distance_pct']):.1f}%")
        if a.get("ma_52w_distance_pct") is not None:
            text_lines.append(f"  52w MA: {'below' if a.get('ma_52w_below') else 'above'} by {abs(a['ma_52w_distance_pct']):.1f}%")
        if a.get("rsi_weekly") is not None:
            text_lines.append(f"  RSI (weekly): {a['rsi_weekly']:.0f}")
        if a.get("pct_from_52w_high") is not None:
            text_lines.append(f"  From 52w high: {a['pct_from_52w_high']:.1f}%")
        
        text_lines.append("")
        text_lines.append("-" * 60)
        text_lines.append("")
    
    text_lines.append("")
    text_lines.append("View full dashboard: https://nanohzz.github.io/buffett-screener/")
    
    text_body = "\n".join(text_lines)
    
    # ── HTML version ──
    stock_rows = ""
    for a in alerts:
        is_new = a.get("is_new", False)
        new_badge = '<span style="background:#059669;color:white;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700;">NEW</span> ' if is_new else ''
        
        signals_html = ""
        for sig in a.get("entry_signals", []):
            signals_html += f'<div style="font-size:13px;color:#444;padding:2px 0;">{sig}</div>'
        
        combined_color = "#059669" if a.get("combined_score", 0) >= 75 else "#d97706" if a.get("combined_score", 0) >= 70 else "#dc2626"
        
        ma_200w_text = ""
        if a.get("ma_200w_distance_pct") is not None:
            direction = "below" if a.get("ma_200w_below") else "above"
            color = "#059669" if a.get("ma_200w_below") else "#d97706"
            ma_200w_text = f'<span style="color:{color};font-weight:600;">{direction} 200w MA by {abs(a["ma_200w_distance_pct"]):.1f}%</span>'
        
        ma_52w_text = ""
        if a.get("ma_52w_distance_pct") is not None:
            direction = "below" if a.get("ma_52w_below") else "above"
            color = "#059669" if a.get("ma_52w_below") else "#888"
            ma_52w_text = f'<span style="color:{color};">{direction} 52w MA by {abs(a["ma_52w_distance_pct"]):.1f}%</span>'
        
        currency = "A$" if a.get("currency") == "AUD" else "$"
        
        stock_rows += f'''
        <tr style="border-bottom:1px solid #e8e6e1;">
            <td style="padding:16px 12px;vertical-align:top;">
                <div style="font-size:24px;font-weight:700;color:{combined_color};">{a.get('combined_score', 0):.1f}</div>
                <div style="font-size:10px;color:#888;text-transform:uppercase;">Combined</div>
            </td>
            <td style="padding:16px 12px;vertical-align:top;">
                <div style="font-size:16px;font-weight:700;">{new_badge}{a.get('name', a['ticker'])}</div>
                <div style="font-size:12px;color:#888;margin-top:2px;">{a['ticker']} · {a.get('sector', '')} · {currency}{a.get('current_price', 0):.2f}</div>
                
                <div style="margin-top:8px;display:flex;gap:16px;flex-wrap:wrap;">
                    <div style="font-size:11px;"><span style="color:#888;">Buffett:</span> <strong>{a.get('buffett_score', 0):.1f}</strong></div>
                    <div style="font-size:11px;"><span style="color:#888;">Entry:</span> <strong>{a.get('entry_score', 0):.1f}</strong></div>
                    <div style="font-size:11px;"><span style="color:#888;">P/E:</span> <strong>{_fmt(a.get('pe_trailing'))}</strong></div>
                    <div style="font-size:11px;"><span style="color:#888;">ROE:</span> <strong>{_fmt(a.get('roe'))}%</strong></div>
                    <div style="font-size:11px;"><span style="color:#888;">ROIC:</span> <strong>{_fmt(a.get('roic'))}%</strong></div>
                    <div style="font-size:11px;"><span style="color:#888;">FCF Yield:</span> <strong>{_fmt(a.get('fcf_yield'))}%</strong></div>
                </div>
                
                <div style="margin-top:8px;">
                    {f'<div style="font-size:12px;margin-bottom:2px;">{ma_200w_text}</div>' if ma_200w_text else ''}
                    {f'<div style="font-size:12px;margin-bottom:2px;">{ma_52w_text}</div>' if ma_52w_text else ''}
                    {f'<div style="font-size:12px;color:#888;">RSI: {a["rsi_weekly"]:.0f}</div>' if a.get("rsi_weekly") else ''}
                    {f'<div style="font-size:12px;color:#888;">From 52w high: {a["pct_from_52w_high"]:.1f}%</div>' if a.get("pct_from_52w_high") else ''}
                </div>
                
                {f'<div style="margin-top:8px;padding:8px;background:#f9f7f2;border-radius:4px;">{signals_html}</div>' if signals_html else ''}
            </td>
        </tr>'''
    
    html_body = f'''
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:#faf9f6;margin:0;padding:0;">
        <div style="max-width:640px;margin:0 auto;padding:20px;">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#1a1a2e,#0f3460);padding:24px;border-radius:8px 8px 0 0;">
                <h1 style="color:#faf9f6;font-size:20px;margin:0;">The Oracle's Ledger</h1>
                <div style="color:rgba(250,249,246,0.5);font-size:11px;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px;">Daily Entry Alert — {date_str}</div>
            </div>
            
            <!-- Summary -->
            <div style="background:#1a1a2e;padding:16px 24px;color:#e2b340;font-size:14px;font-weight:600;">
                {count} stock{'s' if count != 1 else ''} with combined score above {threshold:.0f}
            </div>
            
            <!-- Stocks -->
            <div style="background:white;border:1px solid #e8e6e1;border-top:none;">
                <table style="width:100%;border-collapse:collapse;">
                    {stock_rows}
                </table>
            </div>
            
            <!-- Footer -->
            <div style="padding:16px;text-align:center;">
                <a href="https://nanohzz.github.io/buffett-screener/" style="color:#1a1a2e;font-size:13px;">View Full Dashboard →</a>
                <div style="font-size:11px;color:#aaa;margin-top:8px;">
                    Combined Score = 60% Buffett Quality + 40% Entry Timing<br>
                    Screened monthly · Prices updated daily
                </div>
            </div>
        </div>
    </body>
    </html>'''
    
    return subject, text_body, html_body


def send_email(subject: str, text_body: str, html_body: str,
               gmail_address: str, gmail_app_pw: str, to_address: str):
    """Send the alert email via Gmail SMTP."""
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Oracle's Ledger <{gmail_address}>"
    msg["To"] = to_address
    
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_pw)
            server.sendmail(gmail_address, to_address, msg.as_string())
        logger.info(f"Alert email sent to {to_address}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise


def _fmt(val):
    if val is None:
        return "—"
    return f"{val:.1f}"


def run_daily_ping(
    threshold: float = 70.0,
    dry_run: bool = False,
    force_email: bool = False,
    screener_input: str = "data/screener_results.json",
    entry_output: str = "data/entry_signals",
    top_n: int = 75,
):
    """Run the daily entry scan and send alerts."""
    
    logger.info(f"=== Daily Ping System — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    logger.info(f"Threshold: combined score > {threshold}")
    
    # ── Step 1: Run entry scanner ──
    from entry_scanner import run_entry_scanner
    
    results = run_entry_scanner(
        input_file=screener_input,
        top_n=top_n,
        output_name=entry_output,
    )
    
    # ── Step 2: Load entry results with combined scores ──
    entry_path = Path(f"{entry_output}.json")
    if not entry_path.exists():
        logger.error("Entry scanner output not found")
        sys.exit(1)
    
    with open(entry_path) as f:
        entry_data = json.load(f)
    
    # ── Step 3: Find stocks above threshold ──
    alerts = []
    for stock in entry_data.get("stocks", []):
        combined = stock.get("combined_score")
        if combined is not None and combined >= threshold:
            alerts.append(stock)
    
    alerts.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
    
    logger.info(f"Stocks above threshold: {len(alerts)}")
    
    # ── Step 4: Check for new entries ──
    previous_tickers = load_previous_alerts()
    current_tickers = [a["ticker"] for a in alerts]
    new_entries = [t for t in current_tickers if t not in previous_tickers]
    
    for a in alerts:
        a["is_new"] = a["ticker"] in new_entries
    
    logger.info(f"New entries since last alert: {len(new_entries)}")
    
    # Save current state for tomorrow
    save_current_alerts(current_tickers)
    
    # ── Step 5: Print summary ──
    print(f"\n{'=' * 60}")
    print(f"  DAILY PING — {datetime.now().strftime('%d %b %Y')}")
    print(f"  Threshold: combined > {threshold}")
    print(f"  Stocks triggered: {len(alerts)}")
    print(f"  New since yesterday: {len(new_entries)}")
    print(f"{'=' * 60}\n")
    
    for a in alerts:
        new_tag = " 🆕 NEW" if a.get("is_new") else ""
        print(f"  {a.get('combined_score', 0):>5.1f}  {a['ticker']:<10} {a.get('name', '')[:30]:<32}{new_tag}")
    
    if not alerts:
        print("  No stocks above threshold today.")
        print(f"{'=' * 60}\n")
        return
    
    print(f"\n{'=' * 60}\n")
    
    # ── Step 6: Send email ──
    if dry_run:
        logger.info("Dry run — skipping email")
        subject, text_body, html_body = build_alert_email(alerts, threshold)
        # Save HTML preview
        with open("data/alert_preview.html", "w") as f:
            f.write(html_body)
        logger.info("Preview saved to data/alert_preview.html")
        return
    
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_pw = os.environ.get("GMAIL_APP_PW")
    alert_to = os.environ.get("ALERT_EMAIL_TO")
    
    if not all([gmail_address, gmail_app_pw, alert_to]):
        logger.warning("Email credentials not configured. Set GMAIL_ADDRESS, GMAIL_APP_PW, ALERT_EMAIL_TO")
        logger.info("Run with --dry-run to preview without sending")
        return
    
    # Only send if there are new entries, or force is set, or it's the first run
    if new_entries or force_email or not previous_tickers:
        subject, text_body, html_body = build_alert_email(alerts, threshold)
        send_email(subject, text_body, html_body, gmail_address, gmail_app_pw, alert_to)
    else:
        logger.info("No new entries — skipping email (use --force-email to override)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Ping System — Entry alerts")
    parser.add_argument("--threshold", type=float, default=70.0,
                        help="Combined score threshold for alerts (default: 70)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview alerts without sending email")
    parser.add_argument("--force-email", action="store_true",
                        help="Send email even if no new entries")
    parser.add_argument("--input", type=str, default="data/screener_results.json",
                        help="Path to screener results")
    parser.add_argument("--top", type=int, default=75,
                        help="Number of top stocks to scan")
    
    args = parser.parse_args()
    
    run_daily_ping(
        threshold=args.threshold,
        dry_run=args.dry_run,
        force_email=args.force_email,
        screener_input=args.input,
        top_n=args.top,
    )
