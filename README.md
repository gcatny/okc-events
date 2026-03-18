# OKC Super Calendar 🎪

A **fully autonomous, AI-powered community calendar** for Oklahoma City that aggregates events from **55+ official sources**, validates them in real-time, and displays them in a beautiful interactive calendar. No manual data entry. No outdated listings. Just real, verified events happening in OKC.

**Live at:** https://gcatny.github.io/okc-events

---

## Overview

The OKC Super Calendar is a sophisticated event aggregation system that:

✨ **Scrapes 55+ event sources nightly** via Claude AI + web search (Plaza District, Paseo, OKCMOA, Paycom Center, Jones Assembly, Science Museum, Myriad Gardens, hundreds more)

🤖 **Validates events automatically** — day-of-week checks, past date removal, duplicate detection, JavaScript syntax verification, event count sanity checks

🔍 **Discovers new sources** — uses AI to find uncovered OKC event calendars and integrates them

✅ **Reviews community submissions** — AI verifies user-submitted events against official sources before publishing

📅 **Updates daily** — GitHub Actions runs nightly, searches the web, deduplicates against existing events, and injects new listings

🌈 **Beautiful UI** — responsive calendar with color-coded categories (art, music, food, sports, theater, comedy, film, free events, family, culture, civic, running, business, conventions, volunteer)

🔎 **Search & filter** — find events by name, venue, artist, date, or category in seconds

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3 (event scraping & validation) |
| **Frontend** | HTML + CSS + vanilla JavaScript |
| **Language Composition** | 68.2% HTML, 31.8% Python |
| **AI/Scraping** | Claude 3.5 Sonnet + Anthropic Web Search |
| **Automation** | GitHub Actions (nightly schedule) |
| **Hosting** | GitHub Pages (static HTML) |

---

## Repository Structure

```
okc-events/
├── index.html                    # Interactive calendar UI (333 KB)
├── update_events.py              # Nightly event updater (simple version)
├── okc_calendar_agent.py         # Full autonomous agent (advanced version)
├── events.ics                    # iCalendar export (all BASE events)
├── .github/
│   └── workflows/               # GitHub Actions automation
└── README.md
```

### Key Files

- **`index.html`** (68.2% of codebase)
  - Full interactive calendar UI with search, filters, and detail panels
  - Embedded BASE_EVENTS array (500+ curated OKC events)
  - Category-based color coding for visual browsing
  - Community event submission form
  - Mobile-responsive design

- **`okc_calendar_agent.py`** (Advanced ~1600 lines)
  - **7 core modules:**
    1. Nightly event scrape (55+ sources)
    2. New source discovery (web search for uncovered calendars)
    3. Multi-pass validation (day-of-week, dates, duplicates, JS syntax, counts)
    4. Community submission AI review
    5. Build & diff (compare yesterday's data)
    6. Safety gate (abort if validation fails)
    7. Monday report (weekly email summary)

- **`update_events.py`** (Simplified ~980 lines)
  - Lighter-weight nightly updater
  - Runs all 55+ sources
  - Parses/deduplicates events
  - Injects LIVE_EVENTS into HTML

---

## How It Works

### 1. **Nightly Scraping (2 AM CST)**

GitHub Actions triggers `okc_calendar_agent.py`:

```python
# Calls Claude 3.5 Sonnet with web search for each source:
# "Find all upcoming events at Plaza District, Paseo Arts, Paycom Center, 
#  OKC Thunder, Myriad Gardens, Science Museum, etc."

# AI returns JSON array of events with:
{
  "name": "Art After 5 at OKCMOA",
  "venue": "Oklahoma City Museum of Art, OKC",
  "date": "2026-03-19",
  "desc": "Every Thursday 5–8 PM — discounted admission $9.95",
  "cat": "art",
  "confirmed": true,
  "source": "OKCMOA",
  "tickets": "https://okcmoa.com/events",
  "free": false
}
```

### 2. **Validation Pipeline**

Multi-pass checking ensures data quality:

- **Past dates** → Remove (event already happened)
- **Day-of-week** → Verify recurring series (e.g., "Art After 5" must be Thursday)
- **Duplicates** → Match by name + date, keep single instance
- **JS syntax** → Validate embedded event arrays with Node.js
- **Event count** → Sanity check (must have 400+ base events, else abort)
- **Structural integrity** → Verify HTML isn't corrupted
- **Plaza LIVE! dates** → Cross-check against official 2nd Friday schedule

### 3. **Event Deduplication**

Compare new scraped events against BASE_EVENTS:
- Key: `(name.lower().strip()[:60], date)`
- Only new/updated events added to LIVE_EVENTS array

### 4. **Community Submissions**

User submits event via form → AI verifies against official URL:

```python
# Claude checks: Is this real? Is the date correct? 
# Legitimate public event? Any red flags?

# Returns:
{
  "approved": true,
  "confidence": "high",
  "reason": "Verified concert at Tower Theatre on official ticketing site",
  "corrected_date": null,
  "corrected_name": null
}
```

### 5. **HTML Injection**

Update `index.html` with new LIVE_EVENTS:

```javascript
// LIVE_EVENTS last updated: March 18, 2026 (47 new events)
var LIVE_EVENTS_DATE = "March 18, 2026";
var LIVE_EVENTS = [
  {name:"Concert Name",venue:"...",date:"2026-03-20",...},
  ...
];

// Merged into calendar:
var allEvents = BASE.slice();
if (typeof LIVE_EVENTS !== 'undefined') {
  LIVE_EVENTS.forEach(function(ev) { allEvents.push(ev); });
}
```

### 6. **Monday Report**

On Mondays, agent posts to GitHub Actions summary:

```
✅ Nightly Event Update — Monday Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ All 55+ sources completed
✓ 47 new events added (9 removed, 12 updated)
✓ Validation: 0 errors, 3 warnings
✓ Community submissions: 2 approved
✓ Execution time: 12 min 34 sec
```

---

## Event Categories (15 Types)

| Category | Color | Examples |
|----------|-------|----------|
| **Art** | Purple | OKCMOA exhibitions, gallery openings, Art After 5 |
| **Music** | Red | Concerts, live bands, DJ nights |
| **Food & Bar** | Green | Restaurants, wine tastings, food festivals |
| **Sports** | Blue | Thunder games, Dodgers, cycling, running races |
| **Festivals** | Gold | Tulip Festival, Pride, Plaza events |
| **Theater** | Maroon | Musicals, plays, comedy |
| **Comedy** | Teal | Stand-up shows |
| **Film** | Brown | Movie screenings, film festivals |
| **Free Events** | Light Blue | Zero-cost community events |
| **Family & Kids** | Purple | Zoo, kid-friendly shows, family science |
| **Culture & Heritage** | Dark Brown | Cowboy Museum, Red Earth, cultural celebrations |
| **Running & Fitness** | Forest Green | 5Ks, marathons, yoga classes |
| **Civic & Government** | Steel Blue | City council meetings, elections |
| **Industry & Business** | Olive | Chamber luncheons, tech meetups, oil/gas events |
| **Conventions & Expos** | Dark Magenta | GalaxyCon, SoonerCon, trade shows |
| **Volunteer** | Teal | Habitat for Humanity, food bank, cleanups |

---

## 55+ Event Sources

### **Major Districts & Neighborhoods**
- Plaza District (LIVE! on the Plaza, monthly art walks)
- Paseo Arts District (gallery walks, First Friday)
- Downtown OKC & Bricktown
- West Village & Midtown
- OKC Zoo & Scissortail Park

### **Major Venues**
- Paycom Center (concerts, Thunder, family shows)
- The Yale Theater (Candlelight concerts, immersive)
- Jones Assembly (concerts, touring acts)
- Tower Theatre
- The Criterion
- Beer City Music Hall
- Zoo Amphitheatre
- Ponyboy
- The National OKC

### **Museums & Culture**
- OKC Museum of Art (OKCMOA)
- Science Museum Oklahoma
- National Cowboy Museum
- First Americans Museum
- Oklahoma Historical Society
- Oklahoma Contemporary

### **Performing Arts**
- Lyric Theatre (musicals)
- OKC Rep
- OKC Ballet
- OKC Philharmonic
- Civic Center Music Hall
- Painted Sky Opera

### **Food & Lifestyle**
- OKC Restaurant Week
- Sur La Table cooking classes
- Food & dining events
- Coffee & Cars monthly meetups
- OKANA Resort events

### **Sports**
- OKC Thunder (NBA)
- OKC Dodgers (Minor League Baseball)
- OKC FC (USL Soccer)
- OKC Blue (G-League)
- Horse shows & equine events
- Running races & cycling events
- RIVERSPORT kayaking & paddle events

### **Free & Community**
- Metropolitan Library System
- Myriad Botanical Gardens
- OKC Beautiful
- OKC Volunteer events
- Scissortail Park
- Free OKC events

### **Business & Tech**
- OKC Chamber of Commerce
- 36 Degrees North (startup hub)
- The Verge OKC (entrepreneurship)
- 1 Million Cups (weekly entrepreneur meetup)
- Tech & innovation events
- Oil, Gas & Energy industry

### **Festivals & Large Events**
- VisitOKC annual events
- Music festivals (Norman Music Festival, Rocklahoma, WoodyFest)
- State Fair
- Fairpark events
- GalaxyCon & SoonerCon
- Prix de West
- Red Earth Festival

### **Media Aggregators**
- OKC Gazette
- News9 Entertainment
- 405 Magazine
- Eventbrite OKC

---

## Usage

### **For End Users**

1. **Visit** https://gcatny.github.io/okc-events
2. **Search** by event name, venue, or artist
3. **Filter** by category (Art, Music, Food, etc.)
4. **Click events** for full details, venue info, ticket links
5. **Add to Google Calendar** with one click
6. **Submit missing events** via "Submit an Event" form

### **For Developers**

#### Run the nightly updater locally:
```bash
export ANTHROPIC_API_KEY="your-key-here"
python update_events.py
```

#### Run the full autonomous agent:
```bash
export ANTHROPIC_API_KEY="your-key-here"
export IS_MONDAY="true"  # Optional: for Monday report
python okc_calendar_agent.py
```

#### Deploy via GitHub Actions:
Create `.github/workflows/okc-events-daily.yml`:
```yaml
name: OKC Events Nightly Update
on:
  schedule:
    - cron: '0 8 * * *'  # 8 AM UTC = 2 AM CST
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: |
          export ANTHROPIC_API_KEY="${{ secrets.ANTHROPIC_API_KEY }}"
          export IS_MONDAY=$(date +%u | grep -q 1 && echo true || echo false)
          python okc_calendar_agent.py
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: 'chore: update events [automated]'
```

---

## Architecture Decisions

### Why AI + Web Search?

- **No API keys required** from individual venues (many don't have public APIs)
- **Natural language prompting** — AI understands fuzzy requests like "find all upcoming shows"
- **Web search integration** — Claude can search the actual websites in real-time
- **Flexibility** — Easy to add/remove sources by editing SOURCES dictionary
- **Validation** — Claude verifies dates, venues, and details as it scrapes

### Why GitHub Actions?

- **Free** (up to 2,000 minutes/month)
- **Scheduled runs** — Cron jobs for nightly updates
- **No server needed** — Static site hosted on GitHub Pages
- **Version control** — All changes tracked in git

### Why JavaScript (not framework)?

- **No build step** — Pure HTML/CSS/JS, works in any browser
- **Fast** — No React/Vue overhead, instant interactions
- **Portable** — Single HTML file, easy to archive or fork
- **Accessible** — Semantic HTML, keyboard navigation

---

## Performance & Scale

| Metric | Value |
|--------|-------|
| **Calendar size** | 500+ curated BASE events |
| **Nightly updates** | 55+ sources queried |
| **Average new events** | 40–60 per night |
| **Validation speed** | ~1 sec per event |
| **Total agent runtime** | 10–15 minutes |
| **Calendar load time** | <500ms (static HTML) |
| **Search speed** | Real-time (JavaScript) |
| **Mobile support** | Full responsive design |

---

## Future Enhancements

- 📱 **Native mobile app** (iOS/Android)
- 📤 **iCalendar sync** (import into Outlook/Apple Calendar)
- 🗺️ **Map view** with venue locations
- 📧 **Email alerts** for new events by category/venue
- 🤝 **Venue partner integrations** (direct API feeds)
- 🌐 **Multi-language support** (Spanish, Vietnamese)
- 🔐 **User accounts** (saved favorites, watchlists)
- 📊 **Analytics dashboard** (event trends, popular categories)

---

## Contributing

To add an event source or improve the calendar:

1. **Fork** the repo
2. **Edit** `okc_calendar_agent.py` or `update_events.py` to add your source
3. **Test** locally with your API key
4. **Submit a pull request** with a description

Event submissions are reviewed via the form on the site — no coding needed!

---

## License

MIT License — feel free to fork, modify, and use for your own city's calendar.

---

## Contact & Support

- **Issues**: https://github.com/gcatny/okc-events/issues
- **Submit event**: Use the "Submit an Event" button on the calendar
- **Questions**: Comment on an issue

---

## Credits

Built with ❤️ for Oklahoma City using Claude AI + GitHub Actions.

Inspired by the vibrant OKC community and the desire for a single, accurate, always-updated event calendar.

**Contributors**: @gcatny

---

*Last updated: March 18, 2026*
*Next update: March 19, 2026 at 2:00 AM CST*
