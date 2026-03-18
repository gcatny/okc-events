#!/usr/bin/env python3
"""
OKC Super Calendar — Autonomous Agent
======================================
Runs nightly via GitHub Actions. Does everything needed to keep the
calendar accurate, growing, and error-free without human intervention.

MODULES:
  1. Nightly event scrape  — all 55+ known sources
  2. New source discovery  — web searches for OKC event pages not yet tracked
  3. Multi-pass validation — day-of-week, past dates, duplicates, JS syntax,
                             event count sanity, Plaza/recurring series checks
  4. Community submission review — AI verifies pending user submissions
  5. Build + diff          — counts added/removed/changed vs yesterday
  6. Safety gate           — abort and keep previous if checks fail
  7. Monday report         — weekly summary emailed via GitHub summary

ENVIRONMENT VARIABLES REQUIRED:
  ANTHROPIC_API_KEY   — for Claude API calls
  GITHUB_STEP_SUMMARY — auto-set by GitHub Actions (for report output)
  IS_MONDAY           — set to "true" in workflow on Mondays
"""

import os, json, re, time, datetime, sys, subprocess, copy
import urllib.request, urllib.error

# ── CONFIG ────────────────────────────────────────────────────────────────────

API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
TODAY     = datetime.date.today()
TODAY_STR = TODAY.strftime("%B %d, %Y")
CUTOFF    = TODAY.isoformat()
IS_MONDAY = os.environ.get("IS_MONDAY", "").lower() == "true"
HTML_PATH = "index.html"
LOG_PATH  = "agent_log.json"

if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)

VALID_CATS = {
    "art","music","food","sports","fest","theater","comedy",
    "film","free","family","culture","running","civic","industry","convention"
}

# Day-of-week enforcement for known recurring series
# weekday(): Mon=0 Tue=1 Wed=2 Thu=3 Fri=4 Sat=5 Sun=6
RECURRING_DOW = {
    "art after 5":          {3},        # Thursdays
    "reading wednesday":    {2},        # Wednesdays
    "free yoga at myriad":  {1, 5},     # Tuesdays & Saturdays
    "lively running club":  {2},        # Wednesdays
    "okc farmers public":   {5},        # Saturdays
    "oak farmers market":   {5},        # Saturdays
    "sunday jazz brunch":   {6},        # Sundays
    "afternoon tea: royaltea": {4,5,6}, # Fri/Sat/Sun
    "first friday - paseo": {4},        # Fridays
    "live! on the plaza":   {4},        # Fridays
    "pajama storytime":     {4, 5},     # Fri & Sat
}

# ── JSON INSTRUCTION appended to every source prompt ─────────────────────────

JSON_INSTRUCTION = (
    " Search the web to find REAL confirmed upcoming events. "
    "Return ONLY a raw JSON array with no markdown, no code fences, no preamble. "
    "Each item must have: "
    "name (string), venue (string, include city), date (YYYY-MM-DD), "
    "desc (one concise sentence with time if known), "
    "cat (one of: art|music|food|sports|fest|theater|comedy|film|free|family|"
    "culture|running|civic|industry|convention), "
    "confirmed (true/false), source (string), "
    "tickets (URL string or empty string), free (true/false). "
    "Only include events with confirmed specific dates. "
    "Return array starting with [ and ending with ]. No other text."
)

# ── SOURCES ───────────────────────────────────────────────────────────────────
# Import all sources from update_events.py at runtime so there's one source
# of truth. We exec() it and grab the SOURCES dict.

def load_sources():
    """Load SOURCES dict from update_events.py."""
    src_code = open("update_events.py").read()
    # Extract just the SOURCES dict and JSON_INSTRUCTION
    ns = {}
    try:
        exec(src_code, ns)
        return ns.get("SOURCES", {})
    except Exception as e:
        print(f"Warning: could not exec update_events.py ({e}), using empty sources")
        return {}

# ── API HELPERS ───────────────────────────────────────────────────────────────

def call_api(system_prompt, user_msg=None, max_tokens=2000,
             use_search=True, retries=2):
    """Call Anthropic API, optionally with web search."""
    tools = [{"type": "web_search_20250305", "name": "web_search"}] if use_search else []
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "tools": tools if tools else None,
        "system": system_prompt,
        "messages": [{
            "role": "user",
            "content": user_msg or (
                "Use your web search tool to find real upcoming events "
                "from this source. Search the actual website URLs mentioned. "
                "Return only the JSON array of events."
            )
        }]
    }, default=lambda x: None).encode()
    # Remove None tool list if not used
    payload_dict = json.loads(payload)
    if not tools:
        payload_dict.pop("tools", None)
    payload = json.dumps(payload_dict).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "web-search-2025-03-05"
        },
        method="POST"
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
                text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return text
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"    HTTP {e.code}: {body[:200]}")
            if e.code in (529, 503, 500) and attempt < retries:
                wait = 30 * (attempt + 1)
                print(f"    Retrying in {wait}s...")
                time.sleep(wait)
            else:
                return None
        except Exception as e:
            print(f"    Error: {e}")
            if attempt < retries:
                time.sleep(15)
            else:
                return None
    return None


# ── PARSING ───────────────────────────────────────────────────────────────────

def parse_events(text, source_label):
    """Extract and validate JSON event array from API response."""
    if not text:
        return []
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("[")
    end   = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        events = json.loads(text[start:end + 1])
        valid = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if not ev.get("name") or not ev.get("date"):
                continue
            try:
                date_str = str(ev["date"]).strip()
                if len(date_str) < 10 or date_str < CUTOFF:
                    continue
                ev["date"] = date_str[:10]
            except Exception:
                continue
            ev["source"]    = ev.get("source") or source_label
            ev["confirmed"] = bool(ev.get("confirmed", False))
            ev["free"]      = bool(ev.get("free", False))
            ev["tickets"]   = str(ev.get("tickets") or "").strip()
            cat = str(ev.get("cat", "fest")).lower().strip()
            ev["cat"] = cat if cat in VALID_CATS else "fest"
            for field in ("name", "venue", "desc", "source"):
                ev[field] = str(ev.get(field, "")).replace("\\", "\\\\").strip()
            valid.append(ev)
        return valid
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        return []


def dedup_events(new_events, existing_keys):
    """Remove events already present by name+date key."""
    seen = set()
    result = []
    for ev in new_events:
        key = (ev["name"].lower().strip()[:60], ev.get("date", ""))
        if key not in existing_keys and key not in seen:
            seen.add(key)
            result.append(ev)
    return result


# ── MODULE 2: NEW SOURCE DISCOVERY ───────────────────────────────────────────

DISCOVERY_PROMPT = """
You are a researcher finding NEW event sources for the OKC Super Calendar —
a community calendar for Oklahoma City Metro area.

We already track 55+ sources including: Plaza District, Paseo, Civic Center,
Tower Theatre, OKCMOA, Myriad Gardens, RIVERSPORT, OKANA Resort, Zoo,
Science Museum, OKC Thunder, Dodgers, Ballet, Lyric Theatre, deadCenter Film,
GalaxyCon, SoonerCon, Rocklahoma, Route 66, Eventbrite OKC, and many more.

Search the web for Oklahoma City event pages and community calendars that are:
1. NOT already in our sources above
2. Actively posting upcoming 2026 events
3. Genuinely community-relevant (not private corporate events)
4. High quality sources with real confirmed dates

Focus on finding:
- Neighborhood associations with event calendars
- Cultural organizations (Native American, Hispanic, Asian, LGBTQ+, etc.)
- Sports leagues or recreational clubs
- Food/restaurant event series
- Art galleries or creative spaces
- Fitness studios with community classes
- Community foundations or nonprofits
- New venues that opened in 2025/2026

Today is {today}.

Return a JSON array of new sources to investigate. Each item:
{{
  "name": "Source name",
  "url": "URL of their events page",
  "category": "brief category",
  "why": "one sentence on why this is worth adding"
}}

Return only the JSON array. Max 10 new sources per run.
""".strip()


def discover_new_sources(existing_source_urls):
    """Search for new OKC event sources not yet tracked."""
    print("\n[MODULE 2: New source discovery]")
    prompt = DISCOVERY_PROMPT.replace("{today}", TODAY_STR) + JSON_INSTRUCTION

    text = call_api(prompt, use_search=True, max_tokens=1500,
                    user_msg="Search for new Oklahoma City community event sources "
                             "not already in our calendar. Return JSON array.")
    if not text:
        print("  Discovery search failed")
        return []

    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("[")
    end   = text.rfind("]")
    if start == -1 or end == -1:
        print("  No discovery results")
        return []

    try:
        sources = json.loads(text[start:end + 1])
        new = []
        for s in sources:
            if not isinstance(s, dict):
                continue
            url = str(s.get("url", "")).lower()
            if not url:
                continue
            # Check it's not already tracked
            already_tracked = any(
                existing.lower() in url or url in existing.lower()
                for existing in existing_source_urls
            )
            if not already_tracked:
                new.append(s)
        print(f"  Found {len(new)} potentially new sources")
        for s in new[:5]:
            print(f"    + {s.get('name')}: {s.get('url')}")
        return new
    except Exception as e:
        print(f"  Discovery parse error: {e}")
        return []


def fetch_events_from_new_source(source):
    """Try to get events from a newly discovered source."""
    prompt = (
        f"You find upcoming community events listed at {source.get('url')} "
        f"in Oklahoma City, OK. This is {source.get('name')} — {source.get('why', '')}. "
        f"Search the page for upcoming public events in 2026. "
        f"Today is {TODAY_STR}. Return events for the next 90 days. "
        f"Only include in-person OKC metro events with confirmed dates."
    ) + JSON_INSTRUCTION

    text = call_api(prompt, use_search=True, max_tokens=1500)
    if not text:
        return []
    events = parse_events(text, source.get("name", "New Source"))
    return events


# ── MODULE 3: MULTI-PASS VALIDATION ──────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.passed       = True
        self.errors       = []
        self.warnings     = []
        self.fixed        = []
        self.events_removed = 0
        self.events_fixed   = 0

    def error(self, msg):
        self.errors.append(msg)
        self.passed = False

    def warn(self, msg):
        self.warnings.append(msg)

    def fix(self, msg):
        self.fixed.append(msg)
        self.events_fixed += 1


def validate_and_fix(html, live_events):
    """
    Multi-pass validation of the full HTML + new live events.
    Returns (fixed_html, fixed_events, ValidationResult).
    """
    result = ValidationResult()
    fixed  = []

    # ── PASS 1: Past date purge ──────────────────────────────────────────────
    for ev in live_events:
        d_str = ev.get("date", "")
        try:
            if d_str < CUTOFF:
                result.fix(f"Removed past event: {ev.get('name')} ({d_str})")
                result.events_removed += 1
                continue
        except Exception:
            pass
        fixed.append(ev)
    live_events = fixed
    fixed = []

    # ── PASS 2: Day-of-week check for recurring series ────────────────────────
    dow_errors = 0
    for ev in live_events:
        name_lower = ev.get("name", "").lower()
        d_str      = ev.get("date", "")
        matched    = False
        for pattern, valid_days in RECURRING_DOW.items():
            if pattern in name_lower:
                matched = True
                try:
                    d = datetime.datetime.strptime(d_str, "%Y-%m-%d")
                    if d.weekday() not in valid_days:
                        day_names = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}
                        actual    = day_names[d.weekday()]
                        expected  = "/".join(day_names[x] for x in sorted(valid_days))
                        result.warn(
                            f"DOW mismatch: '{ev.get('name')}' on {d_str} ({actual}) "
                            f"— expected {expected}. Skipping."
                        )
                        dow_errors += 1
                        ev = None
                except Exception:
                    pass
                break
        if ev is not None:
            fixed.append(ev)
    live_events = fixed
    fixed = []
    if dow_errors:
        result.fix(f"Removed {dow_errors} events with wrong day-of-week")

    # ── PASS 3: Duplicate dedup within new events ────────────────────────────
    seen_keys = set()
    dupe_count = 0
    for ev in live_events:
        key = (ev.get("name", "").lower().strip()[:60], ev.get("date", ""))
        if key in seen_keys:
            dupe_count += 1
            continue
        seen_keys.add(key)
        fixed.append(ev)
    live_events = fixed
    fixed = []
    if dupe_count:
        result.fix(f"Removed {dupe_count} duplicate events from new batch")

    # ── PASS 4: JS syntax check ──────────────────────────────────────────────
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    if scripts:
        test_js = "\n".join(scripts)
        try:
            with open("/tmp/agent_syntax_check.js", "w") as f:
                f.write(test_js)
            r = subprocess.run(
                ["node", "--check", "/tmp/agent_syntax_check.js"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0:
                result.error(f"JS syntax error: {r.stderr[:300]}")
        except FileNotFoundError:
            result.warn("node not available — skipping JS syntax check")
        except Exception as e:
            result.warn(f"JS syntax check failed: {e}")

    # ── PASS 5: Event count sanity check ────────────────────────────────────
    base_count = len(re.findall(r'name:"[^"]+",venue:', html))
    if base_count < 400:
        result.error(
            f"Sanity check failed: only {base_count} events in HTML "
            f"(expected 400+). Possible corruption — aborting."
        )

    # ── PASS 6: Structural integrity ────────────────────────────────────────
    for tag, expected in [("<body", 1), ("</html>", 1), ("<style", 1)]:
        count = html.count(tag)
        if count != expected:
            result.error(
                f"Structural error: found {count}x '{tag}' "
                f"(expected {expected}). File may be duplicated."
            )

    # ── PASS 7: Plaza LIVE! date sanity (2nd Friday check) ─────────────────
    # Official 2026 dates from plazadistrict.org
    official_plaza = {
        "2026-04-10","2026-05-08","2026-06-12","2026-07-10",
        "2026-08-14","2026-09-11","2026-10-09"
    }
    for ev in live_events:
        if "live" in ev.get("name","").lower() and "plaza" in ev.get("name","").lower():
            if ev.get("date") and ev["date"] not in official_plaza:
                d = datetime.datetime.strptime(ev["date"], "%Y-%m-%d")
                if d.weekday() != 4:  # not a Friday
                    result.warn(
                        f"Plaza LIVE! event on non-Friday: {ev['name']} {ev['date']} "
                        f"({d.strftime('%A')})"
                    )

    return html, live_events, result


# ── MODULE 4: COMMUNITY SUBMISSION REVIEW ────────────────────────────────────

VERIFY_PROMPT = """
You are a community event verifier for the OKC Super Calendar.

A user submitted this event:
Name:    {name}
Date:    {date}
Venue:   {venue}
Details: {desc}
URL:     {url}

Please verify this event by searching the web. Check:
1. Is this a real event at a real OKC metro venue on this date?
2. Is the date correct (right day of week for recurring events)?
3. Is this a legitimate public community event (not MLM, not private)?
4. Are there any red flags (spam, fake venue, wrong city)?

Search for the event name + venue name to confirm it's real.

Respond ONLY with a JSON object:
{{
  "approved": true/false,
  "confidence": "high"/"medium"/"low",
  "reason": "one sentence explanation",
  "corrected_date": "YYYY-MM-DD or null if date is correct",
  "corrected_name": "corrected name or null if correct"
}}
""".strip()


def review_pending_submissions(html):
    """
    Find pending user submissions in the HTML and AI-verify them.
    Returns updated html with approved events moved to LIVE_EVENTS
    and a report dict.
    """
    print("\n[MODULE 4: Community submission review]")

    # Extract pending events from localStorage-style data in the page
    # The admin panel stores pending events as JS in the page
    pending_match = re.search(
        r'var PENDING_EVENTS\s*=\s*(\[.*?\]);',
        html, re.DOTALL
    )
    if not pending_match:
        print("  No pending submissions found")
        return html, {"reviewed": 0, "approved": 0, "rejected": 0, "details": []}

    try:
        pending = json.loads(pending_match.group(1))
    except Exception:
        print("  Could not parse pending events")
        return html, {"reviewed": 0, "approved": 0, "rejected": 0, "details": []}

    if not pending:
        print("  Pending queue is empty")
        return html, {"reviewed": 0, "approved": 0, "rejected": 0, "details": []}

    print(f"  Found {len(pending)} pending submission(s)")
    approved_events = []
    rejected = []
    report_details = []

    for sub in pending:
        name  = sub.get("name", "")
        date  = sub.get("date", "")
        venue = sub.get("venue", "")
        desc  = sub.get("desc", "")
        url   = sub.get("url", "")

        print(f"  Reviewing: '{name}' on {date}")

        prompt = VERIFY_PROMPT.format(
            name=name, date=date, venue=venue, desc=desc, url=url
        )
        text = call_api(prompt, use_search=True, max_tokens=500,
                        user_msg=f"Search the web to verify this event: {name} at {venue} on {date}. "
                                  "Return only the JSON verification object.")

        if not text:
            print(f"    Could not verify — flagging for human review")
            report_details.append({"name": name, "date": date,
                                    "result": "unverified", "reason": "API call failed"})
            continue

        text = re.sub(r"```(?:json)?", "", text).strip()
        try:
            obj_start = text.find("{")
            obj_end   = text.rfind("}") + 1
            verdict   = json.loads(text[obj_start:obj_end])
        except Exception:
            print(f"    Parse error on verification response")
            report_details.append({"name": name, "date": date,
                                    "result": "unverified", "reason": "Parse error"})
            continue

        if verdict.get("approved") and verdict.get("confidence") in ("high", "medium"):
            print(f"    APPROVED ({verdict.get('confidence')}) — {verdict.get('reason')}")
            # Apply any corrections
            if verdict.get("corrected_date"):
                sub["date"] = verdict["corrected_date"]
            if verdict.get("corrected_name"):
                sub["name"] = verdict["corrected_name"]
            sub["confirmed"] = True
            sub["source"] = sub.get("source", "Community Submission (AI-verified)")
            approved_events.append(sub)
            report_details.append({"name": name, "date": date,
                                    "result": "approved",
                                    "reason": verdict.get("reason", "")})
        else:
            print(f"    REJECTED — {verdict.get('reason')}")
            rejected.append(sub)
            report_details.append({"name": name, "date": date,
                                    "result": "rejected",
                                    "reason": verdict.get("reason", "")})
        time.sleep(2)

    report = {
        "reviewed": len(pending),
        "approved": len(approved_events),
        "rejected": len(rejected),
        "details":  report_details
    }
    print(f"  Reviewed {len(pending)}: {len(approved_events)} approved, {len(rejected)} rejected")
    return html, report, approved_events


# ── MODULE 5: BUILD + DIFF ────────────────────────────────────────────────────

def events_to_js(events):
    """Serialize event list to JS array literal."""
    lines = []
    for ev in events:
        def esc(s):
            return str(s).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'  {{name:"{esc(ev.get("name",""))}",venue:"{esc(ev.get("venue",""))}",date:"{ev.get("date","")}",',
            f'desc:"{esc(ev.get("desc",""))}",cat:"{ev.get("cat","fest")}",',
            f'confirmed:{"true" if ev.get("confirmed") else "false"},',
            f'source:"{esc(ev.get("source",""))}",tickets:"{esc(ev.get("tickets",""))}",',
            f'free:{"true" if ev.get("free") else "false"}}}'
        )
        # Fix: lines.append takes a single string
    lines = []
    for ev in events:
        def esc(s):
            return str(s).replace("\\", "\\\\").replace('"', '\\"')
        line = (
            f'  {{name:"{esc(ev.get("name",""))}",venue:"{esc(ev.get("venue",""))}",'
            f'date:"{ev.get("date","")}",'
            f'desc:"{esc(ev.get("desc",""))}",cat:"{ev.get("cat","fest")}",'
            f'confirmed:{"true" if ev.get("confirmed") else "false"},'
            f'source:"{esc(ev.get("source",""))}",tickets:"{esc(ev.get("tickets",""))}",'
            f'free:{"true" if ev.get("free") else "false"}}}'
        )
        lines.append(line)
    return "[\n" + ",\n".join(lines) + "\n]"


def compute_diff(old_html, new_html):
    """Compare event counts between old and new HTML."""
    def count_events(h):
        return len(re.findall(r'name:"[^"]+",venue:', h))

    def get_event_keys(h):
        keys = set()
        for m in re.finditer(r'name:"([^"]+)",venue:"[^"]*",date:"([^"]+)"', h):
            keys.add((m.group(1).lower()[:50], m.group(2)))
        return keys

    old_count  = count_events(old_html)
    new_count  = count_events(new_html)
    old_keys   = get_event_keys(old_html)
    new_keys   = get_event_keys(new_html)
    added      = new_keys - old_keys
    removed    = old_keys - new_keys

    return {
        "old_count": old_count,
        "new_count": new_count,
        "added":     len(added),
        "removed":   len(removed),
        "net":       new_count - old_count,
        "added_sample":   list(added)[:5],
        "removed_sample": list(removed)[:5],
    }


# ── MODULE 6: MONDAY REPORT ───────────────────────────────────────────────────

def write_monday_report(run_stats):
    """Write a detailed weekly summary to GitHub Actions step summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    lines = []

    lines.append("# 📅 OKC Super Calendar — Weekly Agent Report")
    lines.append(f"**Generated:** {TODAY_STR}  |  **Day:** Monday\n")

    # Events summary
    diff = run_stats.get("diff", {})
    lines.append("## 📊 This week's calendar stats")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total events in calendar | {diff.get('new_count', '—')} |")
    lines.append(f"| Events added this run | +{diff.get('added', 0)} |")
    lines.append(f"| Events removed (past/invalid) | -{diff.get('removed', 0)} |")
    lines.append(f"| Net change | {diff.get('net', 0):+d} |")
    lines.append(f"| Sources scraped | {run_stats.get('sources_run', 0)} |")
    lines.append(f"| Failed sources | {len(run_stats.get('failed_sources', []))} |")

    # New sources discovered
    new_srcs = run_stats.get("new_sources_found", [])
    if new_srcs:
        lines.append("\n## 🔍 New sources discovered this week")
        for s in new_srcs[:10]:
            lines.append(f"- **{s.get('name')}** — {s.get('url')}")
            lines.append(f"  *{s.get('why', '')}*")
    else:
        lines.append("\n## 🔍 New sources\nNo new sources found this run.")

    # Community submissions
    sub_report = run_stats.get("submission_report", {})
    if sub_report.get("reviewed", 0) > 0:
        lines.append("\n## 👥 Community submissions reviewed")
        lines.append(f"- Reviewed: {sub_report.get('reviewed', 0)}")
        lines.append(f"- Approved: {sub_report.get('approved', 0)}")
        lines.append(f"- Rejected: {sub_report.get('rejected', 0)}")
        for d in sub_report.get("details", []):
            icon = "✅" if d["result"] == "approved" else "❌" if d["result"] == "rejected" else "⚠️"
            lines.append(f"  {icon} **{d['name']}** ({d['date']}) — {d['reason']}")
    else:
        lines.append("\n## 👥 Community submissions\nNo submissions in queue.")

    # Validation results
    val = run_stats.get("validation", {})
    fixes = val.get("fixed", [])
    warnings = val.get("warnings", [])
    errors = val.get("errors", [])
    if fixes or warnings or errors:
        lines.append("\n## 🔧 Validation & auto-fixes")
        for f in fixes[:10]:
            lines.append(f"- 🔧 {f}")
        for w in warnings[:10]:
            lines.append(f"- ⚠️ {w}")
        for e in errors[:5]:
            lines.append(f"- ❌ {e}")
    else:
        lines.append("\n## 🔧 Validation\nAll checks passed — no issues found.")

    # Failed sources
    failed = run_stats.get("failed_sources", [])
    if failed:
        lines.append("\n## ⚠️ Failed sources (may need attention)")
        for s in failed:
            lines.append(f"- {s}")

    # Publish prompt
    lines.append("\n---")
    lines.append("## 🚀 Ready to publish")
    lines.append(
        "A new `index.html` has been automatically committed to the repo. "
        "GitHub Pages will deploy it within ~10 minutes — no action needed.\n\n"
        "To manually verify before it goes live, check the Actions tab for "
        "the diff summary above. If anything looks wrong, you can revert the "
        "last commit in the GitHub repo."
    )

    report_text = "\n".join(lines)

    # Write to GitHub Actions step summary
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(report_text + "\n")
            print("\n[MODULE 7: Monday report written to GitHub Actions summary]")
        except Exception as e:
            print(f"  Could not write to step summary: {e}")

    # Also print to stdout for the Actions log
    print("\n" + "="*60)
    print("MONDAY WEEKLY REPORT")
    print("="*60)
    print(report_text)

    return report_text


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"OKC Calendar Agent — {TODAY_STR}")
    print(f"Monday mode: {IS_MONDAY}")
    print(f"{'='*60}\n")

    # Load HTML
    if not os.path.exists(HTML_PATH):
        print(f"ERROR: {HTML_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        original_html = f.read()

    html = original_html

    # Snapshot for diff
    old_html_snapshot = html

    run_stats = {
        "date":             TODAY_STR,
        "is_monday":        IS_MONDAY,
        "sources_run":      0,
        "failed_sources":   [],
        "new_events_added": 0,
        "new_sources_found":[],
        "submission_report":{},
        "validation":       {},
        "diff":             {},
    }

    # ── Build existing key set for dedup ──────────────────────────────────────
    base_keys = set()
    for m in re.finditer(r'\{name:"([^"]+)",venue:"[^"]*",date:"([^"]+)"', html):
        base_keys.add((m.group(1).lower().strip()[:60], m.group(2)))
    print(f"Loaded {len(base_keys)} existing events for dedup\n")

    # ── MODULE 1: Scrape all known sources ────────────────────────────────────
    print("[MODULE 1: Scraping known sources]")
    SOURCES = load_sources()
    all_new_events = []
    failed_sources = []

    for source_id, source_info in SOURCES.items():
        label  = source_info["label"]
        system = source_info["system"].replace("{today}", TODAY_STR) + JSON_INSTRUCTION
        print(f"  [{label}]")
        text = call_api(system)
        if text is None:
            print(f"    x Failed")
            failed_sources.append(label)
            time.sleep(2)
            continue
        events     = parse_events(text, label)
        new_events = dedup_events(events, base_keys)
        print(f"    {len(events)} found → {len(new_events)} new")
        all_new_events.extend(new_events)
        for ev in new_events:
            base_keys.add((ev["name"].lower().strip()[:60], ev.get("date", "")))
        time.sleep(2)

    run_stats["sources_run"]    = len(SOURCES)
    run_stats["failed_sources"] = failed_sources
    print(f"\n  Total from known sources: {len(all_new_events)} new events")
    print(f"  Failed: {len(failed_sources)}")

    # ── MODULE 2: New source discovery ───────────────────────────────────────
    existing_urls = [s.get("system", "") for s in SOURCES.values()]
    new_sources   = discover_new_sources(existing_urls)
    run_stats["new_sources_found"] = new_sources

    discovery_events = []
    for source in new_sources[:5]:  # Limit to 5 new sources per run
        print(f"  Fetching from new source: {source.get('name')}")
        evs = fetch_events_from_new_source(source)
        new = dedup_events(evs, base_keys)
        print(f"    {len(evs)} found → {len(new)} new")
        discovery_events.extend(new)
        for ev in new:
            base_keys.add((ev["name"].lower().strip()[:60], ev.get("date", "")))
        time.sleep(2)

    all_new_events.extend(discovery_events)
    print(f"  From new sources: {len(discovery_events)} additional events")

    # ── MODULE 3: Validate + fix new events ───────────────────────────────────
    print("\n[MODULE 3: Multi-pass validation]")

    # Build a test HTML with the new events injected to validate JS
    test_live_js = events_to_js(all_new_events) if all_new_events else "[]"
    test_updated = (
        f'// LIVE_EVENTS last updated: {TODAY_STR}\n'
        f'var LIVE_EVENTS_DATE = "{TODAY_STR}";\n'
        f'var LIVE_EVENTS = {test_live_js};'
    )
    if "var LIVE_EVENTS" in html:
        test_html = re.sub(
            r'// LIVE_EVENTS last updated:.*?var LIVE_EVENTS\s*=\s*\[.*?\];',
            test_updated, html, flags=re.DOTALL
        )
    else:
        test_html = html.replace(
            "</script>", f"{test_updated}\n</script>", 1
        )

    test_html, all_new_events, val_result = validate_and_fix(test_html, all_new_events)

    run_stats["validation"] = {
        "passed":   val_result.passed,
        "errors":   val_result.errors,
        "warnings": val_result.warnings,
        "fixed":    val_result.fixed,
    }

    print(f"  Validation: {'PASSED ✓' if val_result.passed else 'FAILED ✗'}")
    for f in val_result.fixed:
        print(f"    Fixed: {f}")
    for w in val_result.warnings[:5]:
        print(f"    Warn: {w}")
    for e in val_result.errors:
        print(f"    ERROR: {e}")

    if not val_result.passed:
        print("\n⛔ VALIDATION FAILED — keeping previous index.html")
        print("Errors:")
        for e in val_result.errors:
            print(f"  - {e}")
        run_stats["aborted"] = True
        if IS_MONDAY:
            write_monday_report(run_stats)
        sys.exit(0)  # exit 0 so GH Actions doesn't mark as failed

    # ── MODULE 4: Community submissions ──────────────────────────────────────
    sub_result = review_pending_submissions(html)
    if len(sub_result) == 3:
        html, sub_report, approved_events = sub_result
        run_stats["submission_report"] = sub_report
        all_new_events.extend(approved_events)
    else:
        html, sub_report = sub_result
        run_stats["submission_report"] = sub_report

    # ── MODULE 5: Build final HTML ────────────────────────────────────────────
    print(f"\n[MODULE 5: Building index.html]")

    if not all_new_events:
        print("  No new events — writing HTML with empty LIVE_EVENTS")

    all_new_events.sort(key=lambda e: e.get("date", ""))

    live_js = events_to_js(all_new_events)
    updated_str = (
        f'// LIVE_EVENTS last updated: {TODAY_STR} ({len(all_new_events)} events)\n'
        f'var LIVE_EVENTS_DATE = "{TODAY_STR}";\n'
        f'var LIVE_EVENTS = {live_js};'
    )

    if "var LIVE_EVENTS" in html:
        new_html = re.sub(
            r'// LIVE_EVENTS last updated:.*?var LIVE_EVENTS\s*=\s*\[.*?\];',
            updated_str, html, flags=re.DOTALL
        )
    else:
        # First run — inject before closing </script>
        new_html = html.replace("</script>", f"{updated_str}\n</script>", 1)

    # ── Final structural validation ───────────────────────────────────────────
    _, _, final_val = validate_and_fix(new_html, [])
    if not final_val.passed:
        print("\n⛔ FINAL VALIDATION FAILED — keeping previous index.html")
        for e in final_val.errors:
            print(f"  - {e}")
        if IS_MONDAY:
            write_monday_report(run_stats)
        sys.exit(0)

    # ── Compute diff ──────────────────────────────────────────────────────────
    diff = compute_diff(old_html_snapshot, new_html)
    run_stats["diff"]             = diff
    run_stats["new_events_added"] = len(all_new_events)

    print(f"  Events: {diff['old_count']} → {diff['new_count']} "
          f"(+{diff['added']} added, -{diff['removed']} removed)")

    # ── Write output ──────────────────────────────────────────────────────────
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"  ✓ Wrote {HTML_PATH} ({len(new_html):,} bytes)")

    # ── Save agent log ────────────────────────────────────────────────────────
    try:
        logs = []
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH) as f:
                logs = json.load(f)
        logs.append(run_stats)
        logs = logs[-30:]  # Keep last 30 runs
        with open(LOG_PATH, "w") as f:
            json.dump(logs, f, indent=2, default=str)
        print(f"  ✓ Agent log updated ({len(logs)} entries)")
    except Exception as e:
        print(f"  Warning: could not write log: {e}")

    # ── MODULE 7: Monday report ───────────────────────────────────────────────
    if IS_MONDAY:
        write_monday_report(run_stats)

    print(f"\n{'='*60}")
    print(f"✓ Agent run complete — {len(all_new_events)} new events added")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
