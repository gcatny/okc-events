#!/usr/bin/env python3
"""
OKC Super Calendar - Nightly Event Updater
Runs via GitHub Actions. Calls Anthropic API for each source,
collects new events, deduplicates against BASE, and re-bakes
them into index.html as an LIVE_EVENTS array.
"""

import os, json, re, time, datetime, sys
import urllib.request, urllib.error

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)

TODAY = datetime.date.today()
TODAY_STR = TODAY.strftime("%B %d, %Y")
CUTOFF = TODAY.isoformat()  # don't include past events

JSON_INSTRUCTION = (
    " Search the web to find REAL current events. Return ONLY a raw JSON array "
    "with no markdown, no fences, no explanation. Each item must have: "
    "name (string), venue (string), date (YYYY-MM-DD), desc (one sentence), "
    "cat (art|music|food|sports|fest|theater|comedy|film|free|family|culture|"
    "running|civic|industry|convention), confirmed (boolean), source (string), "
    "tickets (URL string or null), free (boolean). "
    "Only return the JSON array starting with [ and ending with ]."
)

SOURCES = {
    'plaza': {'label': 'Plaza District', 'system': 'You find events listed on the Plaza District event calendar at plazadistrict.org/event-calendar in Oklahoma City. Search for all upcoming Plaza District events including LIVE on the Plaza monthly art walks, block parties, festivals, and any special events. Today is {today}. Return events for the next 90 days.'},
    'paseo': {'label': 'Paseo Arts District', 'system': 'You find events listed on thepaseo.org/paseocalendar1 and thepaseo.org for the Paseo Arts District Oklahoma City. Search for all upcoming gallery events, First Friday events, FEAST events, Paseo Arts Awards, workshops, art shows, and special events. Today is {today}. Return events for the next 90 days.'},
    'visitokc': {'label': 'VisitOKC - Annual Events', 'system': 'You find upcoming events from VisitOKC. Search visitokc.com/events, visitokc.com/events/this-month-in-okc, and visitokc.com/events/annual-events for confirmed upcoming Oklahoma City events including festivals, concerts, sports, and cultural happenings. Focus on confirmed events with specific dates. Today is {today}. Return events for the next 90 days.'},
    'concerts': {'label': 'OKC Live Music', 'system': 'You find live music and concert events in Oklahoma City. Search visitokc.com/events/concerts-live-music and local OKC music sites for upcoming shows at Jones Assembly, Tower Theatre, Criterion, Beer City Music Hall, Zoo Amphitheatre, Diamond Ballroom, 89th Street, Paycom Center, and all OKC venues. Today is {today}. Return events for the next 90 days.'},
    'library': {'label': 'Metro Library OKC', 'system': 'You find free events at the Oklahoma Metropolitan Library System. Search metrolibrary.org/events/month for upcoming free community events including author talks, workshops, teen events, film screenings, cultural programs, book clubs, and all public events at OKC metro library branches. Today is {today}. Return events for the next 60 days. Mark all as free:true.'},
    'science': {'label': 'Science Museum OKC', 'system': 'You find events at Science Museum Oklahoma. Search sciencemuseumok.org/smoevents for upcoming events including special exhibitions, IMAX films, family science nights, member events, educational programs, and all public events at Science Museum OKC. Today is {today}. Return events for the next 90 days.'},
    'free': {'label': 'Free OKC Events', 'system': 'You find free events in Oklahoma City Oklahoma. Search for upcoming FREE no-cost events including free concerts, free festivals, free gallery openings, free outdoor movies, free community events in parks, free museum days, free art walks, free library events, free family events, and all no-cost events in OKC. Today is {today}. Return events for the next 90 days. Mark all as free:true and cat:free.'},
    'family': {'label': 'Family & Kids', 'system': 'You find family-friendly and kids events in Oklahoma City Oklahoma. Search for upcoming events at Science Museum OKC, OKC Zoo, Myriad Gardens, children theater shows, family festivals, kids workshops, storytime events, family film screenings, and all family-oriented events in OKC. Today is {today}. Return events for the next 90 days. Mark all as cat:family.'},
    'galas': {'label': 'Galas & Fundraisers', 'system': 'You find upcoming galas, fundraisers, and nonprofit events in Oklahoma City. Search okcnp.org/events, npofoklahoma.com/events, 405magazine.com/events for charity galas, benefit dinners, and nonprofit events in OKC. Also check alliedartsokc.com and similar OKC nonprofit event calendars. Today is {today}. Return events for the next 90 days.'},
    'tulsa': {'label': 'Cains Ballroom Tulsa', 'system': 'You find upcoming shows at Cains Ballroom in Tulsa Oklahoma. Search cainsballroom.com and concert listings for all confirmed concerts, touring acts, and special events at this historic venue at 423 N Main St Tulsa OK. Today is {today}. Return events for the next 90 days.'},
    'paycom': {'label': 'Paycom Center OKC', 'system': 'You find upcoming events at Paycom Center in Oklahoma City at 100 W Reno Ave. Search paycomcenter.com/events for all upcoming concerts, sports, family shows, and special events. Include OKC Thunder games, concerts, PBR, monster trucks, and touring shows. Today is {today}. Return all events for the next 180 days.'},
    'yale': {'label': 'The Yale Theater OKC', 'system': 'You find upcoming events at The Yale Theater in Oklahoma City at 227 SW 25th Street in Capitol Hill. Search theyaleokc.com/upcoming-events for Candlelight concerts, Jazz Room shows, Jury Experience immersive theater, art exhibitions, and special events. Today is {today}. Return events for the next 90 days.'},
    'allied': {'label': 'Allied Arts OKC', 'system': 'You find upcoming Allied Arts Oklahoma City events. Search alliedartsokc.com for ARTini galas, fundraisers, and arts events. Also search for events at Myriad Botanical Gardens and OKC arts nonprofits. Today is {today}. Return events for the next 90 days.'},
    'okgazette': {'label': 'OKC Gazette & News9', 'system': 'You find upcoming Oklahoma City events covered by OKC Gazette (okgazette.com), News9 (news9.com), and Oklahoman (oklahoman.com). Search for newly announced OKC events, restaurant openings, gallery shows, concerts, and festivals. Today is {today}. Return events for the next 60 days.'},
    'downtown': {'label': 'Downtown OKC & Bricktown', 'system': 'You find events in Downtown OKC and Bricktown. Search downtownokc.com, bricktownokc.com, welcometobricktown.com, wheelerdistrict.com for upcoming events, festivals, concerts, and markets in downtown OKC. Today is {today}. Return events for the next 90 days.'},
    'surlatable': {'label': 'Sur La Table OKC Classes', 'system': 'You find upcoming cooking classes at Sur La Table at Classen Curve in Oklahoma City. Search surlatable.com/cooking-classes/in-store-cooking-classes for OKC classes including Date Night, skill building, international cuisines, and baking. Today is {today}. Return classes for the next 60 days.'},
    'conventions': {'label': 'Conventions & Expos OKC', 'system': 'You find upcoming conventions, expos, and trade shows in Oklahoma City. Search okcconventioncenter.com/events, galaxycon.com, horrorconokc.com, soonercon.com, retropalooza.com, brickconvention.com for OKC conventions, comic cons, and expos. Today is {today}. Return events for the next 180 days.'},
    'running': {'label': 'Running & Fitness OKC', 'system': 'You find upcoming running races and fitness events in OKC area. Search okcmarathon.com, okcrunning.org/calendar, riversportokc.org/events, runsignup.com for Oklahoma City races including 5Ks, half marathons, triathlons, and wellness events. Today is {today}. Return events for the next 180 days.'},
    'equine': {'label': 'Horse Shows & Equine OKC', 'system': 'You find upcoming horse shows and equine events in Oklahoma City. Search visitokc.com/events/horse-shows, nrhafuturity.com, okcfairpark.com/schedule, okqha.org/shows for horse shows at OKC Fairpark and State Fair Arena. Include NRHA Futurity, AQHA, and barrel racing events. Today is {today}. Return events for the next 180 days.'},
    'music_fests': {'label': 'Music Festivals Oklahoma', 'system': 'You find upcoming music festivals in Oklahoma. Search normanmusicfestival.com, rocklahoma.com, woodyfest.com, and Oklahoma festival sites. Include Norman Music Festival (Apr 23-25 FREE), Rocklahoma (Sep 4-6 in Pryor), WoodyFest (July in Okemah), Calf Fry (Apr 30-May 2 in Stillwater), and Born & Raised festival. Today is {today}. Return events for the next 180 days.'},
    'theater2': {'label': 'OKC Rep & Civic Center', 'system': 'You find upcoming theater and performing arts in Oklahoma City. Search okcrep.org, okcciviccenter.com/events for plays, musicals, dance, and opera in OKC. Include OKC Rep, Civic Center touring shows, OKC Philharmonic, OKC Ballet, and Lyric Theatre. Today is {today}. Return events for the next 180 days.'},
    'realestate': {'label': 'Real Estate & ULI OKC', 'system': 'You find upcoming real estate, homebuilding, and land use events in Oklahoma City. Search my.okstatehomebuilders.com/events, eventbrite.com/d/ok--oklahoma-city/real-estate-events, uli.org/events for OKC real estate conferences, homebuilder events, and urban land institute programs. Today is {today}. Return events for the next 90 days.'},
    'tech': {'label': 'Tech & Business OKC', 'system': 'You find upcoming tech, startup, and business events in OKC. Search 36degreesnorth.co/events, okcoders.com/events, meetup.com for Oklahoma City tech events, ou.edu/tomlove/events for startup meetups, hackathons, and business conferences. Today is {today}. Return events for the next 90 days.'},
    'film2': {'label': 'Film & Factory Obscura', 'system': 'You find upcoming film screenings and immersive art in OKC. Search factoryobscura.com/events, okcmoa.com/film, deadcenterfilm.org, oklahomafilm.org/events, oklahomacontemporary.org/calendar for film and immersive art events in OKC. Today is {today}. Return events for the next 90 days.'},
    'fairs': {'label': 'Fairs & State Fair OKC', 'system': 'You find upcoming fairs and large public events in OKC. Search okstatefair.com, okcfairpark.com/schedule for the Oklahoma State Fair (Sept 17-27, 2026) and all fair events at OKC Fairpark including livestock shows and special events. Today is {today}. Return events for the next 180 days.'},
    'culture': {'label': 'Cultural & Heritage OKC', 'system': 'You find upcoming cultural and heritage events in OKC. Search nationalcowboymuseum.org/events, okhistory.org/events, firstamericansmuseum.org, asiandistrictok.com/upcoming-events, famok.org for cultural festivals, museum events, and heritage celebrations. Today is {today}. Return events for the next 90 days.'},
    'civic': {'label': 'Civic & Government OKC', 'system': 'You find upcoming civic meetings and public events in Oklahoma City. Search okc.gov/government/city-council/city-council-meetings, okc.gov/government/boards-commissions/meeting-calendar, oklahoma.gov/elections for OKC City Council meetings, planning commission, elections, and civic events. Also search scissortailpark.org/events. Today is {today}. Return events for the next 60 days.'},
    'chamber': {'label': 'OKC Chamber & Business', 'system': 'You find upcoming OKC Chamber of Commerce and business events. Search okcchamber.com/events for chamber luncheons, award ceremonies, Government Affairs events, State Spotlight events, and business networking programs. Today is {today}. Return events for the next 90 days.'},
    'oilandgas': {'label': 'Oil, Gas & Energy OKC', 'system': 'You find upcoming oil, gas, and energy industry events in Oklahoma City. Search okenergytoday.com/events, oklahomaenergy.org/events, spe.org/en/events/conferences for Oklahoma oil and gas conferences, industry mixers, and energy sector events including Petroleum Alliance of Oklahoma events. Today is {today}. Return events for the next 180 days.'},
}

def call_api(system_prompt, retries=2):
    """Call Anthropic API with web search tool."""
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "system": system_prompt + JSON_INSTRUCTION,
        "messages": [{
            "role": "user",
            "content": "Search the web right now to find real upcoming events from this source. Use your web search tool. Return only the JSON array."
        }]
    }).encode()

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
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                # Extract text content from response
                text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return text
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"    HTTP {e.code}: {body[:200]}")
            if e.code == 529 and attempt < retries:
                time.sleep(30)
            else:
                return None
        except Exception as e:
            print(f"    Error: {e}")
            if attempt < retries:
                time.sleep(10)
            else:
                return None
    return None


def parse_events(text, source_label):
    """Extract JSON array from API response text."""
    if not text:
        return []
    # Find JSON array in response
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        events = json.loads(text[start:end+1])
        valid = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if not ev.get("name") or not ev.get("date"):
                continue
            # Filter out past events
            try:
                if ev["date"] < CUTOFF:
                    continue
            except Exception:
                continue
            ev["source"] = ev.get("source", source_label)
            ev["confirmed"] = ev.get("confirmed", False)
            ev["free"] = ev.get("free", False)
            ev["tickets"] = ev.get("tickets") or ""
            ev["cat"] = ev.get("cat", "fest")
            valid.append(ev)
        return valid
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        return []


def dedup_events(new_events, existing_names):
    """Remove events that are already in BASE by name+date."""
    seen = set()
    result = []
    for ev in new_events:
        key = (ev["name"].lower().strip(), ev.get("date", ""))
        if key not in existing_names and key not in seen:
            seen.add(key)
            result.append(ev)
    return result


def events_to_js(events):
    """Convert list of event dicts to JS array literal."""
    lines = []
    for ev in events:
        name = ev.get("name","").replace("\\","\\\\").replace('"','\\"')
        venue = ev.get("venue","").replace("\\","\\\\").replace('"','\\"')
        date = ev.get("date","")
        desc = ev.get("desc","").replace("\\","\\\\").replace('"','\\"')
        cat = ev.get("cat","fest")
        confirmed = "true" if ev.get("confirmed") else "false"
        free = "true" if ev.get("free") else "false"
        source = ev.get("source","").replace("\\","\\\\").replace('"','\\"')
        tickets = ev.get("tickets","").replace("\\","\\\\").replace('"','\\"')
        lines.append(
            f'  {{name:"{name}",venue:"{venue}",date:"{date}",'
            f'desc:"{desc}",cat:"{cat}",confirmed:{confirmed},'
            f'source:"{source}",tickets:"{tickets}",free:{free}}}'
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def main():
    html_path = "index.html"
    if not os.path.exists(html_path):
        print(f"ERROR: {html_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Extract existing BASE event names for dedup
    base_names = set()
    for m in re.finditer(r'\{name:"([^"]+)",venue:"[^"]*",date:"([^"]+)"', html):
        base_names.add((m.group(1).lower().strip(), m.group(2)))
    print(f"Loaded {len(base_names)} existing BASE events for dedup")

    # Query each source
    all_new_events = []
    for source_id, source_info in SOURCES.items():
        label = source_info["label"]
        system = source_info["system"].replace("{today}", TODAY_STR)
        print(f"Searching: {label}...")
        text = call_api(system)
        events = parse_events(text, label)
        new_events = dedup_events(events, base_names)
        print(f"  Found {len(events)} events, {len(new_events)} new after dedup")
        all_new_events.extend(new_events)
        # Add newly found to base_names to avoid cross-source dups
        for ev in new_events:
            base_names.add((ev["name"].lower().strip(), ev.get("date","")))
        time.sleep(1.5)  # be gentle with the API

    print(f"\nTotal new events collected: {len(all_new_events)}")

    if not all_new_events:
        print("No new events found - skipping HTML update")
        return

    # Inject LIVE_EVENTS into HTML
    live_js = events_to_js(all_new_events)
    updated_str = f"// LIVE_EVENTS last updated: {TODAY_STR} ({len(all_new_events)} events)\nvar LIVE_EVENTS_DATE = \"{TODAY_STR}\";\nvar LIVE_EVENTS = {live_js};"

    # Replace existing LIVE_EVENTS block or insert before allEvents
    if "var LIVE_EVENTS" in html:
        html = re.sub(
            r'// LIVE_EVENTS last updated:.*?var LIVE_EVENTS\s*=\s*\[.*?\];',
            updated_str,
            html,
            flags=re.DOTALL
        )
        print("Replaced existing LIVE_EVENTS block")
    else:
        # First run - insert before allEvents
        html = html.replace(
            "\nvar allEvents = BASE.slice();",
            f"\n{updated_str}\n\nvar allEvents = BASE.slice();"
        )
        print("Inserted LIVE_EVENTS block (first run)")

    # Ensure allEvents includes LIVE_EVENTS
    if "LIVE_EVENTS.forEach" not in html:
        html = html.replace(
            "var allEvents = BASE.slice();",
            "var allEvents = BASE.slice();\n"
            "if (typeof LIVE_EVENTS !== 'undefined') {\n"
            "  LIVE_EVENTS.forEach(function(ev) { allEvents.push(ev); });\n"
            "}"
        )
        print("Added LIVE_EVENTS merge into allEvents")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone. index.html updated with {len(all_new_events)} live events.")
    print(f"Updated: {TODAY_STR}")


if __name__ == "__main__":
    main()
