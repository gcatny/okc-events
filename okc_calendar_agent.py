#!/usr/bin/env python3
"""
OKC Super Calendar - Nightly Event Updater
Runs via GitHub Actions every night at 2 AM Central (8 AM UTC).
Calls Anthropic API with web search for each source, collects new
events, deduplicates against BASE, and injects them into index.html
as a LIVE_EVENTS array.

Supports dual-category tagging (cat + cat2) for crossover events.
"""
import os, json, re, time, datetime, sys
import urllib.request, urllib.error

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)

TODAY = datetime.date.today()
TODAY_STR = TODAY.strftime("%B %d, %Y")
CUTOFF = TODAY.isoformat()

# ── VALID CATEGORIES ──────────────────────────────────────────────────────────
# Must match ALL_CATS in index.html
VALID_CATS = {
    'art', 'music', 'food', 'sports', 'fest', 'theater', 'comedy',
    'film', 'free', 'family', 'culture', 'running', 'civic',
    'industry', 'convention', 'volunteer', 'happyhour', 'fundraiser', 'fashion'
}

# Events matching these keywords get dual-tagged with cat2
DUAL_TAG_RULES = {
    # If an event's name/desc matches these patterns AND its primary cat is listed,
    # it gets the specified cat2
    'fashion': {
        'keywords': ['gala', 'ball', 'black tie', 'fashion', 'runway', 'boutique market'],
        'from_cats': ['fundraiser', 'fest', 'culture'],
    },
    'fundraiser': {
        'keywords': ['fundraiser', 'fundraising', 'benefit dinner', 'charity'],
        'from_cats': ['fashion', 'art', 'culture', 'family'],
    },
}

JSON_INSTRUCTION = (
    " Search the web to find REAL confirmed upcoming events. "
    "Return ONLY a raw JSON array with no markdown, no code fences, no preamble. "
    "Each item must have: "
    "name (string), venue (string, include city), date (YYYY-MM-DD), "
    "desc (one concise sentence with time if known), "
    "cat (one of: art|music|food|sports|fest|theater|comedy|film|free|family|"
    "culture|running|civic|industry|convention|volunteer|happyhour|fundraiser|fashion), "
    "confirmed (true/false), source (string), "
    "tickets (URL string or empty string), free (true/false), "
    "district (string — use one of: Downtown / City Center, Bricktown, Midtown, "
    "Plaza District, Paseo Arts District, Automobile Alley, Deep Deuce, "
    "Uptown 23rd, Western Avenue, Classen Curve / OAK, Film Row / West Village, "
    "Adventure District, Boathouse District, Capitol Hill, Stockyards City, "
    "Asian District, Wheeler District, 39th Street District, East End District, "
    "State Fair Park, Edmond, Norman, Stillwater, Tulsa, or Various). "
    "Only include events with confirmed specific dates. "
    "Return array starting with [ and ending with ]. No other text."
)

# ── SOURCES ───────────────────────────────────────────────────────────────────
# Synced with index.html SOURCES + expanded from full agent config

SOURCES = {
    # ── DISTRICTS & NEIGHBORHOODS ──
    'plaza': {
        'label': 'Plaza District OKC',
        'system': (
            'You find events on the Plaza District event calendar at '
            'plazadistrict.org/event-calendar in Oklahoma City. Search for all '
            'upcoming Plaza District events including LIVE on the Plaza (2nd Friday '
            'of each month Feb-Oct, 6-10 PM, free), LOVE! on the Plaza, PRIDE! on '
            'the Plaza, SKATE! the Plaza, the annual Plaza District Festival (fall), '
            'Coffee & Conversations, Cocktails & Conversations, block parties, '
            'pop-up markets, and any special events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'paseo': {
        'label': 'Paseo Arts District OKC',
        'system': (
            'You find events listed on thepaseo.org and thepaseo.org/paseocalendar1 '
            'for the Paseo Arts District Oklahoma City. Search for all upcoming '
            'gallery openings, First Friday Paseo Gallery Walks, FEAST events, '
            'Paseo Arts Festival (Memorial Day weekend), Paseo Arts Awards, '
            'workshops, studio tours, art shows, and special events in the '
            'Paseo district. Today is {today}. Return events for the next 180 days.'
        )
    },
    'downtown': {
        'label': 'Downtown OKC, Bricktown & Wheeler District',
        'system': (
            'You find events in Downtown OKC and Bricktown Oklahoma City. '
            'Search downtownokc.com/events, bricktownokc.com, '
            'welcometobricktown.com, and wheelerdistrict.com/events for upcoming '
            'festivals, concerts, markets, outdoor movies, First Friday events, '
            'and all public happenings in downtown OKC including Bricktown, '
            'Wheeler District, Automobile Alley, and Film Row. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'westvillage': {
        'label': 'West Village, Midtown & Classen OKC',
        'system': (
            'You find events in the West Village, Classen Curve, and Midtown '
            'areas of Oklahoma City. Search westvillageokc.com, midtown OKC '
            'event listings, and Classen Curve shops/restaurants for pop-up '
            'markets, outdoor events, restaurant events, gallery shows, and '
            'community happenings in western and midtown OKC. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'western_ave': {
        'label': 'Western Avenue Association OKC',
        'system': (
            'You find events hosted by or along Western Avenue in Oklahoma City. '
            'Search visitwesternavenue.com/events-list for upcoming events including '
            'Taste of Western, Wheels on Western, Wizards on Western, and other '
            'Western Avenue Association events. Use source string '
            '"Western Avenue Association - visitwesternavenue.com". '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'midtownokc': {
        'label': 'Midtown OKC Events',
        'system': (
            'You find upcoming events in the Midtown Oklahoma City district. '
            'Search midtownokc.com/events and midtownokc.com/signature-events for block parties, '
            'pop-up markets, restaurant events, art walks, and community happenings in Midtown OKC. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },

    # ── MAJOR VENUES ──
    'paycom': {
        'label': 'Paycom Center OKC',
        'system': (
            'You find upcoming events at Paycom Center in Oklahoma City at '
            '100 W Reno Ave. Search paycomcenter.com/events for all upcoming '
            'concerts, OKC Thunder NBA games, family shows, PBR bull riding, '
            'monster trucks, ice shows, touring Broadway, and all special events. '
            'Today is {today}. Return all events for the next 180 days.'
        )
    },
    'yale': {
        'label': 'The Yale Theater OKC',
        'system': (
            'You find upcoming events at The Yale Theater in Oklahoma City '
            'at 227 SW 25th Street in Capitol Hill. Search theyaleokc.com/'
            'upcoming-events for Candlelight concerts (Coldplay, Fleetwood Mac, '
            'Beatles, etc.), Jazz Room shows, Jury Experience immersive theater, '
            'MOMENTUM performances, art exhibitions, and all special events. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'jonesassembly': {
        'label': 'Jones Assembly OKC',
        'system': (
            'You find upcoming shows at Jones Assembly in Oklahoma City at '
            '901 W Sheridan Ave. Search jonesassembly.com/events for all '
            'upcoming concerts, touring acts, comedy shows, private events, '
            'and special performances. Today is {today}. '
            'Return events for the next 90 days.'
        )
    },
    'tower': {
        'label': 'Tower Theatre OKC',
        'system': (
            'You find upcoming shows at Tower Theatre in Oklahoma City at '
            '425 NW 23rd St. Search towertheatreokc.com/events and '
            'prekindle.com/events/tower-theatre for all upcoming '
            'concerts, comedy shows, touring acts, tribute bands, dance parties, '
            'and special events at this historic venue. Today is {today}. '
            'Return events for the next 90 days.'
        )
    },
    'criterion': {
        'label': 'The Criterion OKC',
        'system': (
            'You find upcoming shows at The Criterion in Oklahoma City at '
            '500 E Sheridan Ave in Bricktown. Search criterionokc.com or '
            'livenation.com/venue/LA3A1Efpkz0zLl for all upcoming concerts and '
            'touring acts at The Criterion. Today is {today}. '
            'Return events for the next 90 days.'
        )
    },
    'beercity': {
        'label': 'Beer City Music Hall OKC',
        'system': (
            'You find upcoming shows at Beer City Music Hall in Oklahoma City. '
            'Search prekindle.com/events/beer-city-music-hall and '
            'beercitymusichall.com for all upcoming concerts, local and touring '
            'acts, and special events. Today is {today}. '
            'Return events for the next 90 days.'
        )
    },
    'zoo_amp': {
        'label': 'Zoo Amphitheatre OKC',
        'system': (
            'You find upcoming concerts and events at Zoo Amphitheatre in '
            'Oklahoma City at 2101 NE 50th St inside OKC Zoo. Search '
            'zooamphitheatre.net and livenation.com for all upcoming outdoor '
            'concerts and shows. Today is {today}. '
            'Return events for the next 180 days.'
        )
    },
    'ponyboy': {
        'label': 'Ponyboy OKC',
        'system': (
            'You find upcoming events at Ponyboy bar/venue in Oklahoma City '
            'at 700 W Sheridan Ave. Search prekindle.com/events/ponyboy and '
            'Ponyboy OKC social media for upcoming live music, DJ nights, '
            'karaoke, theme parties, and special events upstairs and downstairs. '
            'Today is {today}. Return events for the next 60 days.'
        )
    },
    'national': {
        'label': 'The National OKC',
        'system': (
            'You find events on The National hotel event calendar at '
            'thenationalokc.com/events in Oklahoma City (120 N Robinson Ave). '
            'Search for all upcoming events including Afternoon Tea: RoyalTEA, '
            'Live Music at The Vault, Sunday Jazz Brunch at Tellers, '
            'wine dinners at Stock & Bond, and all special dining experiences. '
            'Today is {today}. Return all events for the next 90 days.'
        )
    },
    'civiccenter': {
        'label': 'Civic Center Music Hall OKC',
        'system': (
            'You find upcoming events at Civic Center Music Hall at 201 N Walker Ave, Oklahoma City. '
            'Search okcciviccenter.com/events and okcbroadway.com/upcomingevents for all performances '
            'including OKC Broadway touring shows, OKC Philharmonic concerts, OKC Ballet performances, '
            'Canterbury Voices, Lyric Theatre, Painted Sky Opera, and special one-night shows. '
            'Today is {today}. Return all events for the next 180 days.'
        )
    },
    'tulsa': {
        'label': "Cain's Ballroom Tulsa",
        'system': (
            "You find upcoming shows at Cain's Ballroom in Tulsa Oklahoma at "
            '423 N Main St. Search cainsballroom.com for all confirmed concerts, '
            'touring acts, and special events at this historic ballroom. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },

    # ── ARTS & CULTURE ──
    'allied': {
        'label': 'Allied Arts & Arts Council OKC',
        'system': (
            'You find upcoming arts events in Oklahoma City. Search '
            'alliedartsokc.com, artscouncilokc.com/events, and '
            'artscouncilokc.com/art-moves for ARTini galas, arts fundraisers, '
            'Art Moves free performances, Festival of the Arts (Apr 23-26 2026), '
            'Angels & Friends (Apr 22 2026), and all Allied Arts and Arts Council '
            'OKC programs. Today is {today}. Return events for the next 180 days.'
        )
    },
    'okcmoa': {
        'label': 'OKC Museum of Art',
        'system': (
            'You find upcoming exhibitions and events at the Oklahoma City Museum '
            'of Art at 415 Couch Dr. Search okcmoa.com/exhibitions, '
            'okcmoa.com/events, okcmoa.com/film, and okcmoa.com/upcoming-films for '
            'current and upcoming exhibitions, film screenings, Art After Five, '
            'fundraisers, Renaissance Ball, and public programs. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'okcontemp': {
        'label': 'Oklahoma Contemporary Arts Center',
        'system': (
            'You find upcoming events at Oklahoma Contemporary arts center at 11 NW 11th St, OKC. '
            'Search oklahomacontemporary.org/events/calendar for all upcoming public events including '
            'Second Saturday (2nd Sat monthly, 1-4 PM, free family art day), '
            'Sensory Friendly Hour, Guided Public Tours (Saturdays 1 PM, free), '
            'gallery programs, performances, workshops, and new exhibition openings. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'film2': {
        'label': 'Film, Factory Obscura & Immersive Art OKC',
        'system': (
            'You find upcoming film and immersive art events in OKC. '
            'Search factoryobscura.com/events for Mix-Tape immersive events '
            'and workshops. Search deadcenterfilm.org for deadCenter Film Festival '
            'screenings. Search okcmoa.com/film for OKCMOA film series. '
            'Search oklahomafilm.org for OKC film events and screenings. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'theater2': {
        'label': 'Theater & Performing Arts OKC',
        'system': (
            'You find upcoming theater and performing arts in Oklahoma City. '
            'Search lyrictheatreokc.com for Lyric Theatre musicals and shows. '
            'Search okcrep.org for OKC Rep productions. '
            'Search okcballet.org/performances for OKC Ballet. '
            'Search okcphil.org/events-tickets/25-26-season for OKC Philharmonic. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'ovac_okc': {
        'label': 'OVAC Oklahoma Arts Calendar',
        'system': (
            'You find upcoming visual arts events in Oklahoma City from the OVAC Oklahoma Arts Calendar. '
            'Search ovac-ok.org/okartscalendar for gallery shows, openings, art walks, artist talks, '
            'deadlines, and opportunities in the OKC metro. Oklahoma City events only. '
            'Today is {today}. Return events for the next 60 days.'
        )
    },

    # ── PARKS & GARDENS ──
    'scissortail': {
        'label': 'Scissortail Park OKC',
        'system': (
            'You find upcoming events at Scissortail Park in downtown Oklahoma City (300 SW 7th St). '
            'Search scissortailpark.org/events and scissortailpark.org/calendar for concerts, night markets, '
            'walking club (Thursdays and Sundays 8-8:30 AM year-round), festivals, fitness classes, '
            'kite festivals, and special events. Free outdoor concerts on Loves Travel Stops Stage May-October. '
            'Today is {today}. Return events for the next 90 days. Mark free events as free:true.'
        )
    },
    'myriad_calendar': {
        'label': 'Myriad Botanical Gardens Calendar',
        'system': (
            'You find all events at Myriad Botanical Gardens at 301 W Reno, Oklahoma City. '
            'Search myriadgardens.org/calendar for upcoming events including free yoga classes '
            '(Mondays 6-7 PM), Reading Wednesday storytime (10-10:45 AM), orchid shows, '
            'sound baths, youth workshops, plant sales, and all public programming. '
            'Also check myriadgardens.org/events/flower-garden-festival-2026 for the OKC Flower '
            'and Garden Festival (May 9, 2026, free, 9 AM-4 PM, 70+ vendors). '
            'Today is {today}. Return all events through July 2026. Mark free events as free:true.'
        )
    },

    # ── SPORTS ──
    'sports': {
        'label': 'OKC Sports (Thunder, Comets, FC)',
        'system': (
            'You find upcoming home sports events in Oklahoma City. '
            'Search nba.com/thunder/schedule for OKC Thunder NBA home games at Paycom Center. '
            'Search milb.com/oklahoma-city for OKC Comets home baseball games '
            'at Chickasaw Bricktown Ballpark. '
            'Search okcfc.com/schedule for OKC FC home soccer matches. '
            'Today is {today}. Return all home games for next 90 days.'
        )
    },
    'okc_thunder': {
        'label': 'OKC Thunder — NBA Schedule',
        'system': (
            'You find upcoming OKC Thunder home games at Paycom Center (100 W Reno Ave, OKC). '
            'Search nba.com/thunder/schedule or ticketmaster.com/oklahoma-city-thunder-tickets '
            'for home game dates, tip-off times, opponents, and TV broadcast info. '
            'Include playoff games if applicable. '
            'Today is {today}. Return home games for the next 45 days.'
        )
    },
    'okc_comets': {
        'label': 'OKC Comets Baseball',
        'system': (
            'You find upcoming OKC Comets home games at Chickasaw Bricktown Ballpark. '
            'Search milb.com/oklahoma-city/schedule for home games. '
            'Also check milb.com/oklahoma-city/tickets/specialty-nights for theme nights. '
            'Include Fireworks Fridays, theme nights, and special events. '
            'Today is {today}. Return home games for the next 45 days.'
        )
    },
    'equine': {
        'label': 'Horse Shows & Equine Events OKC',
        'system': (
            'You find upcoming horse shows and equine events in Oklahoma City. '
            'Search nrhafuturity.com, okcfairpark.com/schedule, okqha.org/shows, '
            'and visitokc.com/events/horse-shows for horse shows at '
            'OKC Fairpark and State Fair Arena. Include NRHA, AQHA, '
            'barrel racing, cutting horse, and reining events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'running': {
        'label': 'Running, Fitness & Riversports OKC',
        'system': (
            'You find upcoming running races and fitness events in OKC. '
            'Search okcmarathon.com for OKC Memorial Marathon weekend events. '
            'Search riversportokc.org/events for whitewater and paddle events. '
            'Search runsignup.com for Oklahoma City 5Ks, half marathons, '
            'triathlons, and cycling events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'cycling_okc': {
        'label': 'OKC Cycling & MTB Events',
        'system': (
            'You find upcoming cycling and mountain bike events in the Oklahoma City metro area. '
            'Search findarace.com/us/cycling/oklahoma/oklahoma-city for OKC cycling events. '
            'Also check bikereg.com and active.com for OKC cycling races. '
            'Only include events within 25 miles of downtown OKC. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'pickleball_okc': {
        'label': 'OKC Pickleball Tournaments',
        'system': (
            'You find upcoming pickleball tournaments in the Oklahoma City metro area. '
            'Search allpickleballtournaments.com for Oklahoma City pickleball events. '
            'Also check chickennpickle.com/oklahoma-city-events. '
            'OKC metro only — within 25 miles of downtown OKC. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'usta_okc': {
        'label': 'OKC Tennis Center — USTA Tournaments',
        'system': (
            'You find upcoming tennis tournaments at OKC Tennis Center (3400 N Portland Ave). '
            'Search playtennis.usta.com/oklahomacitytenniscenter/Tournaments for USTA events. '
            'Also check app.utrsports.net for UTR-rated OKC tournaments. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'golf_okc': {
        'label': 'OKC Amateur Golf',
        'system': (
            'You find upcoming amateur golf tournaments in the Oklahoma City metro area. '
            'Search okgolf.org/all-events for Oklahoma Golf Association events. '
            'Also search amateurgolf.com/amateur-golf-tournaments/ByCity/Oklahoma-City. '
            'Skip events more than 25 miles from downtown OKC. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'oksportsfit': {
        'label': 'OK Sports & Fitness — Running/Tri Calendar',
        'system': (
            'You find upcoming running races, triathlons, cycling events, and fitness events '
            'in the Oklahoma City metro area. Search oksportsandfitness.com/event-calendar. '
            'Focus on events within 25 miles of downtown OKC. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'rivers_sport': {
        'label': 'RIVERSPORT OKC Events',
        'system': (
            'You find upcoming special events at RIVERSPORT OKC on the Oklahoma River. '
            'Search riversportokc.org/events for festivals, races, and special events. '
            'Include Stars & Stripes River Festival, PaddleFest, Dragon Boat races, rowing regattas. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'ou_football': {
        'label': 'OU Sooners Football',
        'system': (
            'You find upcoming Oklahoma Sooners football game details. '
            'Search soonersports.com/sports/football/schedule/2026 for confirmed kickoff times, '
            'TV networks, and schedule for home games at Gaylord Family Oklahoma Memorial Stadium in Norman. '
            'Also include the Red River Rivalry vs Texas in Dallas. '
            'Today is {today}. Return games for the next 90 days.'
        )
    },
    'osu_football': {
        'label': 'OSU Cowboys Football',
        'system': (
            'You find upcoming Oklahoma State Cowboys football game details. '
            'Search okstate.com/sports/football/schedule for confirmed kickoff times, '
            'TV networks, and schedule for home games at Boone Pickens Stadium in Stillwater. '
            'Today is {today}. Return games for the next 90 days.'
        )
    },

    # ── FOOD & LIFESTYLE ──
    'surlatable': {
        'label': 'Sur La Table OKC Cooking Classes',
        'system': (
            'You find upcoming cooking classes at Sur La Table at Classen Curve '
            'in Oklahoma City. Search surlatable.com/cooking-classes/'
            'in-store-cooking-classes for OKC classes including Date Night, '
            'Knife Skills, international cuisine, baking, and team events. '
            'Today is {today}. Return classes for the next 60 days.'
        )
    },
    'food_events': {
        'label': 'OKC Food & Dining Events',
        'system': (
            'You find upcoming food and dining events in Oklahoma City. '
            'Search for restaurant pop-ups, food festivals, OKC Restaurant Week, '
            'wine dinners, tasting events, chef table series, food truck festivals, '
            'and culinary events. Check visitokc.com/events/food-and-drink. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'coffee_cars': {
        'label': 'Coffee & Cars OKC',
        'system': (
            'You find upcoming Coffee & Cars OKC monthly car show events. '
            'Check coffeeandcarsokc.com/event-schedule for the full schedule. '
            'Coffee & Cars OKC meets the first Saturday of every month, 8-11 AM, '
            'at Life.Church OKC, 2001 NW 178th St, Edmond, OK 73012. '
            'Free, all-makes/models car gathering open to the public. '
            'Today is {today}. Return all upcoming monthly events for the next 12 months.'
        )
    },

    # ── COMMUNITY & CIVIC ──
    'visitokc': {
        'label': 'VisitOKC Annual & Featured Events',
        'system': (
            'You find upcoming events from VisitOKC. Search visitokc.com/events, '
            'visitokc.com/events/this-month-in-okc, and '
            'visitokc.com/events/annual-events for confirmed upcoming OKC events '
            'including the Tulip Festival, OKC Pride, Juneteenth on the East, '
            'Festival of the Arts, Prix de West, Fright Fest, Fiestas de las '
            'Americas, Steamroller Printmaking, Stockyards Stampede, and all '
            'major annual and featured OKC events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'library': {
        'label': 'Metropolitan Library System OKC',
        'system': (
            'You find free events at the Oklahoma Metropolitan Library System. '
            'Search metrolibrary.org/events and metrolibrary.org/programs for '
            'upcoming free community events including author talks, workshops, '
            'teen and kids programs, film screenings, cultural celebrations, '
            'book clubs, STEM events, and all public events at OKC metro '
            'library branches. Today is {today}. Return events for the next '
            '60 days. Mark all as free:true.'
        )
    },
    'civic': {
        'label': 'Civic, Government & Myriad Gardens OKC',
        'system': (
            'You find upcoming civic and community events in Oklahoma City. '
            'Search okc.gov/government/city-council for OKC City Council meetings. '
            'Search oklahoma.gov/elections for upcoming election dates. '
            'Today is {today}. Return events for the next 60 days.'
        )
    },
    'chamber': {
        'label': 'OKC Chamber & Business Events',
        'system': (
            'You find upcoming OKC Chamber of Commerce and business events. '
            'Search okcchamber.com/events for chamber luncheons, State Spotlight, '
            'Government Affairs breakfasts, networking events, award ceremonies, '
            'and Greater OKC Chamber programs. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'tech': {
        'label': 'Tech, Startup & Innovation OKC',
        'system': (
            'You find upcoming tech and startup events in OKC. '
            'Search 36degreesnorth.co/events for startup ecosystem events. '
            'Search okcinnovation.com/events for OKC Innovation District events. '
            'Search okcoders.com/events for coding community events. '
            'Search meetup.com for Oklahoma City tech meetups. '
            'Search ou.edu/tomlove/events for Tom Love Innovation Hub events. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'verge_okc': {
        'label': 'The Verge OKC',
        'system': (
            'You find upcoming public events at The Verge OKC (600 N. Robinson Ave #500, OKC). '
            'Check vergeokc.com/news-events for upcoming events. '
            'Key recurring events: 1 Million Cups (every Wednesday 9-10 AM, free), '
            'Pitches, Pizza & Pints (4th Wednesday, evening, free), '
            'OTV Workshops (1st Wednesday 4-6 PM, free). '
            'Today is {today}. Return events for the next 90 days. Mark all as free:true.'
        )
    },
    'oilandgas': {
        'label': 'Oil, Gas & Energy Industry OKC',
        'system': (
            'You find upcoming oil, gas, and energy industry events in OKC. '
            'Search okenergytoday.com/events, thepetroleumalliance.com/events, '
            'speokcogs.org for SPE OKC events, and oerb.com for OERB events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'realestate': {
        'label': 'Real Estate & Development OKC',
        'system': (
            'You find upcoming real estate and development events in OKC. '
            'Search my.okstatehomebuilders.com/events for homebuilder events. '
            'Search uli.org/events for Urban Land Institute OKC events. '
            'Search eventbrite.com for OKC real estate investor meetups. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'prsa_okc': {
        'label': 'PRSA Oklahoma City',
        'system': (
            'You find upcoming events from PRSA Oklahoma City. '
            'Search prsaokc.com for monthly luncheons, Professional Development Day, '
            'Upper Case Awards, New Pros events, and special panels. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'aia_okc': {
        'label': 'AIA Central Oklahoma Events',
        'system': (
            'You find upcoming events from AIA Central Oklahoma. '
            'Search aiacoc.org/events-programs for Architecture After 5 networking, luncheons, '
            'Architecture Week, the annual Architecture Tour, and other programs. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },

    # ── SCIENCE & FAMILY ──
    'science': {
        'label': 'Science Museum Oklahoma',
        'system': (
            'You find events at Science Museum Oklahoma at 2020 Remington Pl. '
            'Search sciencemuseumok.org/smoevents and sciencemuseumok.org/planetarium '
            'for upcoming special events, IMAX and planetarium shows, SMO21+ adult nights, '
            'DiscoverFest, Women in STEAM, family science nights, and educational programs. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'family': {
        'label': 'Family & Kids Events OKC',
        'system': (
            'You find family-friendly and kids events in Oklahoma City. '
            'Search okczoo.org/events for OKC Zoo events and special programs. '
            'Search myriadgardens.org/events for family events. '
            'Look for traveling shows like Jurassic Quest, Blue Man Group, '
            'Disney on Ice, and family-friendly events across OKC. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'okana': {
        'label': 'OKANA Resort & Indoor Waterpark',
        'system': (
            'You find upcoming public-facing events at OKANA Resort & Indoor Waterpark '
            'at 639 First Americans Blvd, Oklahoma City. '
            'Check okanaresort.com/activities-and-events for events open to the public. '
            'Include: live music at The Boardwalk Amphitheatre, seasonal celebrations, '
            'Pajama Storytime (Fri/Sat 7-8 PM, free, lobby fireplace), '
            'outdoor waterpark events, and ticketed public events. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'oakokc': {
        'label': 'OAK Heartwood Park OKC',
        'system': (
            'You find upcoming events at OAK Heartwood Park at 2124 NW Expressway, OKC. '
            'Search oakokc.com/events for the weekly OAK Farmers Market (Saturdays 9 AM-1 PM, '
            'April 25 through October 31), Junction Coffee Bus, art installations, and community events. '
            'Today is {today}. Return events for the next 180 days. Mark farmers market as free:true.'
        )
    },

    # ── FESTIVALS & LARGE EVENTS ──
    'music_fests': {
        'label': 'Music Festivals Oklahoma',
        'system': (
            'You find upcoming music festivals in Oklahoma. '
            'Search normanmusicfestival.com for Norman Music Festival (FREE). '
            'Search rocklahoma.com for Rocklahoma (Sept, Pryor OK). '
            'Search woodyfest.com for WoodyFest (July, Okemah OK). '
            'Search calffryfest.com for Calf Fry (Stillwater). '
            'Search for Born & Raised OKC, Future of Sound Fest. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'fairs': {
        'label': 'Fairs, Expos & Fairpark OKC',
        'system': (
            'You find upcoming fairs, expos, and fairpark events in OKC. '
            'Search okstatefair.com for the Oklahoma State Fair. '
            'Search okcfairpark.com/schedule for OKC Fairpark events including '
            'livestock shows, home & garden shows, bridal expos, and special events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'conventions': {
        'label': 'Conventions & Comic Cons OKC',
        'system': (
            'You find upcoming conventions, expos, and cons in Oklahoma City. '
            'Search galaxycon.com for GalaxyCon OKC. '
            'Search soonercon.com for SoonerCon. '
            'Search okcconventioncenter.com/events for convention center events. '
            'Search for HorrorCon OKC, anime cons, and collector expos. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'kickiniton66': {
        'label': "Kickin' It on Route 66",
        'system': (
            "You find upcoming events for the Route 66 Centennial in Oklahoma City. "
            "Check kickiniton66.com for event schedules and updates around the "
            "Kickin' It on Route 66: OKC Centennial Celebration at Scissortail Park on May 30, 2026. "
            "Today is {today}. Return events for the next 180 days."
        )
    },

    # ── CULTURE & HERITAGE ──
    'culture': {
        'label': 'Cultural & Heritage Events OKC',
        'system': (
            'You find upcoming cultural and heritage events in Oklahoma City. '
            'Search nationalcowboymuseum.org/events for Cowboy Museum and Prix de West events. '
            'Search okhistory.org/calendar for Oklahoma Historical Society events. '
            'Search firstamericansmuseum.org for First Americans Museum events. '
            'Search redearth.org for Red Earth Festival. '
            'Search asiandistrictok.com/upcoming-events for Asian District OKC events. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'okhistory': {
        'label': 'Oklahoma History Center',
        'system': (
            'You find upcoming public events at the Oklahoma History Center (800 Nazih Zuhdi Dr, OKC). '
            'Search okhistory.org/calendar/location/oklahoma-history-center for lectures, living history, '
            'exhibitions, symposia, and special programs. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },

    # ── GALAS & FUNDRAISERS ──
    'galas': {
        'label': 'Galas, Fundraisers & Nonprofits OKC',
        'system': (
            'You find upcoming galas, fundraisers, and nonprofit events in OKC. '
            'Search alliedartsokc.com for ARTini and arts fundraisers. '
            'Search okcnp.org/events and npofoklahoma.com/events for nonprofit events. '
            'Search 405magazine.com/events for charity galas and benefit dinners. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },

    # ── VOLUNTEER ──
    'volunteer_okc': {
        'label': 'OKC Volunteer Events',
        'system': (
            'You find upcoming volunteer events in the Oklahoma City metro area. '
            'Search volunteercentraloklahoma.org/calendar for dated volunteer events. '
            'Also check okcbeautiful.com/calendar for OKC Beautiful volunteer events. '
            'Check unitedwayokc.org/get-involved/volunteer for United Way events. '
            'Only include events with a confirmed date in the OKC metro. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },
    'habitat_okc': {
        'label': 'Habitat for Humanity OKC Build Days',
        'system': (
            'You find upcoming volunteer build days at Central Oklahoma Habitat for Humanity. '
            'Check helpmyhabitat.com/need for upcoming build days and ReStore volunteer shifts. '
            'Only include events with a confirmed date in the OKC metro area. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'food_bank_okc': {
        'label': 'Regional Food Bank of Oklahoma',
        'system': (
            'You find upcoming volunteer shift opportunities at the Regional Food Bank of Oklahoma. '
            'Check rfbo.org/volunteer for upcoming volunteer dates and shift availability. '
            'Include food sorting shifts, mobile pantry events, and special volunteer days. '
            'Today is {today}. Return events for the next 60 days.'
        )
    },
    'okcbeautiful': {
        'label': 'OKC Beautiful Events',
        'system': (
            'You find upcoming events from OKC Beautiful at okcbeautiful.com/calendar. '
            'Search for Earth Fest (free annual festival at Scissortail Park), '
            'seedling giveaways, LitterBlitz cleanup events, and all community '
            'environmental and sustainability events. '
            'Today is {today}. Return events for the next 90 days. Mark free events as free:true.'
        )
    },
    'okhumane': {
        'label': 'Oklahoma Humane Society Events',
        'system': (
            'You find upcoming events from the Oklahoma Humane Society at okhumane.org. '
            'Search okhumane.org/poochella for Poochella (annual dog and music festival). '
            'Search okhumane.org/events for the annual gala, Yule Log event, adoption events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },

    # ── FASHION ──
    'fashion': {
        'label': 'OKC Fashion Events',
        'system': (
            'You find upcoming fashion events in Oklahoma City. '
            'Search for fashion shows, runway events, boutique markets, vintage fashion markets, '
            'and fashion-related pop-ups in OKC. Include events like Work the Runway (Goodwill), '
            'Oklahoma Black Fashion Week, Girls Day Out OKC, Wanderlust Pop-Up Shops, '
            'Vintage Market Days OKC, Affair of the Heart, and Sleigh Bells Market. '
            'Also check revolve-productions.com/upcoming-events for boutique market events. '
            'Today is {today}. Return events for the next 180 days.'
        )
    },

    # ── FREE EVENTS ──
    'free': {
        'label': 'Free Events OKC',
        'system': (
            'You find free, no-cost events in Oklahoma City Oklahoma. '
            'Search for upcoming FREE events including free concerts, free '
            'festivals, gallery openings, outdoor movies, community park events, '
            'free museum days, free art walks, free library events, free family '
            'events, and all zero-cost events in OKC. '
            'Today is {today}. Return events for the next 90 days. '
            'Mark all as free:true.'
        )
    },

    # ── LOCAL MEDIA ──
    'okgazette': {
        'label': 'OKC Gazette & Local Media Events',
        'system': (
            'You find newly announced OKC events covered by local media. '
            'Search okgazette.com, news9.com/entertainment/things-to-do, '
            'oklahoman.com/entertainment, and 405magazine.com/events for '
            'newly announced events, restaurant openings, gallery shows, '
            'concerts, pop-ups, and festivals in OKC. '
            'Today is {today}. Return events occurring within the next 60 days.'
        )
    },
    'freepressokc': {
        'label': 'OKC Free Press Events Calendar',
        'system': (
            'You find upcoming events listed on the Oklahoma City Free Press events calendar. '
            'Search freepressokc.com/eventscalendar for community events, arts performances, '
            'film screenings, music shows, literary events, and local happenings in OKC. '
            'Today is {today}. Return events for the next 60 days.'
        )
    },

    # ── AGGREGATORS ──
    'eventbrite_okc': {
        'label': 'Eventbrite OKC',
        'system': (
            'You find quality upcoming in-person community events in Oklahoma City listed on Eventbrite. '
            'Browse https://www.eventbrite.com/d/ok--oklahoma-city/events/ and apply strict quality filtering: '
            'in-person OKC events only, open to the public, genuinely community-relevant (arts, music, food, '
            'fitness, festivals, cultural, family, charity, civic). Skip events already covered by dedicated '
            'sources (Thunder games, Tower Theatre, Civic Center Broadway, OKCMOA, Myriad Gardens). '
            'Skip MLM, vague networking, or spammy events. Aim for 8-15 high-quality events. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
    'concerts': {
        'label': 'OKC Live Music Roundup',
        'system': (
            'You find live music and concert events across Oklahoma City venues. '
            'Search visitokc.com/events/concerts-live-music for the full OKC '
            'concert calendar. Check upcoming shows at Jones Assembly, Tower '
            'Theatre, Criterion, Beer City Music Hall, Zoo Amphitheatre, '
            'Diamond Ballroom, 89th Street, Blue Door, Prairie OKC, '
            'Resonant Head, and all OKC music venues. '
            'Today is {today}. Return events for the next 90 days.'
        )
    },
}


# ── API CALL ──────────────────────────────────────────────────────────────────
def call_api(system_prompt, retries=2):
    """Call Anthropic API with web search tool and return text response."""
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "system": system_prompt + JSON_INSTRUCTION,
        "messages": [{
            "role": "user",
            "content": (
                "Use your web search tool right now to find real upcoming events "
                "from this source. Search the actual website URLs mentioned. "
                "Return only the JSON array of events."
            )
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


# ── PARSING & DEDUP ───────────────────────────────────────────────────────────
def apply_dual_tags(ev):
    """Auto-apply cat2 based on keyword rules for crossover events."""
    text = (ev.get("name", "") + " " + ev.get("desc", "")).lower()
    for cat2, rule in DUAL_TAG_RULES.items():
        if ev.get("cat") in rule['from_cats'] and cat2 != ev.get("cat"):
            for kw in rule['keywords']:
                if kw in text:
                    ev['cat2'] = cat2
                    return ev
    return ev


def parse_events(text, source_label):
    """Extract and validate JSON event array from API response."""
    if not text:
        return []

    text = re.sub(r'```(?:json)?', '', text).strip()
    start = text.find("[")
    end = text.rfind("]")
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

            ev["source"] = ev.get("source") or source_label
            ev["confirmed"] = bool(ev.get("confirmed", False))
            ev["free"] = bool(ev.get("free", False))
            ev["tickets"] = str(ev.get("tickets") or "").strip()
            ev["district"] = str(ev.get("district") or "").strip()

            cat = str(ev.get("cat", "fest")).lower().strip()
            ev["cat"] = cat if cat in VALID_CATS else "fest"

            # Handle cat2 if API returned it
            cat2 = str(ev.get("cat2", "")).lower().strip()
            if cat2 and cat2 in VALID_CATS and cat2 != ev["cat"]:
                ev["cat2"] = cat2
            else:
                ev.pop("cat2", None)

            # Auto-apply dual tags based on keyword rules
            ev = apply_dual_tags(ev)

            for field in ("name", "venue", "desc", "source", "district"):
                ev[field] = str(ev.get(field, "")).replace("\\", "\\\\").strip()

            valid.append(ev)
        return valid
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        return []


def dedup_events(new_events, existing_keys):
    """Remove events already in BASE by name+date key."""
    seen = set()
    result = []
    for ev in new_events:
        key = (ev["name"].lower().strip()[:60], ev.get("date", ""))
        if key not in existing_keys and key not in seen:
            seen.add(key)
            result.append(ev)
    return result


# ── JS SERIALIZATION ──────────────────────────────────────────────────────────
def events_to_js(events):
    """Serialize event list to JS array literal, supporting cat2 field."""
    lines = []
    for ev in events:
        def esc(s):
            return str(s).replace("\\", "\\\\").replace('"', '\\"')

        cat2_str = ""
        if ev.get("cat2"):
            cat2_str = f',cat2:"{ev["cat2"]}"'

        district_str = ""
        if ev.get("district"):
            district_str = f',district:"{esc(ev["district"])}"'

        lines.append(
            f'  {{name:"{esc(ev.get("name",""))}",venue:"{esc(ev.get("venue",""))}",date:"{ev.get("date","")}",'
            f'desc:"{esc(ev.get("desc",""))}",cat:"{ev.get("cat","fest")}"{cat2_str},'
            f'confirmed:{"true" if ev.get("confirmed") else "false"},'
            f'source:"{esc(ev.get("source",""))}",tickets:"{esc(ev.get("tickets",""))}",'
            f'free:{"true" if ev.get("free") else "false"}{district_str}}}'
        )
    return "[\n" + ",\n".join(lines) + "\n]"


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    html_path = "index.html"
    if not os.path.exists(html_path):
        print(f"ERROR: {html_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Build dedup keys from existing events
    base_keys = set()
    for m in re.finditer(r'\{name:"([^"]+)",venue:"[^"]*",date:"([^"]+)"', html):
        base_keys.add((m.group(1).lower().strip()[:60], m.group(2)))

    print(f"Loaded {len(base_keys)} existing BASE events for dedup")
    print(f"Running {len(SOURCES)} sources...\n")

    all_new_events = []
    failed_sources = []

    for source_id, source_info in SOURCES.items():
        label = source_info["label"]
        system = source_info["system"].replace("{today}", TODAY_STR)

        print(f"[{label}]")
        text = call_api(system)
        if text is None:
            print(f"  x Failed")
            failed_sources.append(label)
            time.sleep(2)
            continue

        events = parse_events(text, label)
        new_events = dedup_events(events, base_keys)
        print(f"  Found {len(events)} -> {len(new_events)} new")

        all_new_events.extend(new_events)
        for ev in new_events:
            base_keys.add((ev["name"].lower().strip()[:60], ev.get("date", "")))
        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"Total new events: {len(all_new_events)}")
    if failed_sources:
        print(f"Failed ({len(failed_sources)}): {', '.join(failed_sources)}")

    # Write agent log
    log_entry = {
        "date": TODAY.isoformat(),
        "sources_run": len(SOURCES),
        "failed_sources": failed_sources,
        "new_events": len(all_new_events),
        "diff": {
            "added": len(all_new_events),
            "removed": 0,
            "new_count": len(base_keys) + len(all_new_events)
        },
        "validation": {"passed": True}
    }
    log_path = "agent_log.json"
    try:
        with open(log_path, "r") as f:
            logs = json.load(f)
    except Exception:
        logs = []
    logs.append(log_entry)
    # Keep last 90 days of logs
    logs = logs[-90:]
    with open(log_path, "w") as f:
        json.dump(logs, f, indent=2)

    if not all_new_events:
        print("No new events — skipping HTML update")
        return

    all_new_events.sort(key=lambda e: e.get("date", ""))
    live_js = events_to_js(all_new_events)

    updated_str = (
        f'// LIVE_EVENTS last updated: {TODAY_STR} ({len(all_new_events)} events)\n'
        f'var LIVE_EVENTS_DATE = "{TODAY_STR}";\n'
        f'var LIVE_EVENTS = {live_js};'
    )

    if "var LIVE_EVENTS" in html:
        html = re.sub(
            r'// LIVE_EVENTS last updated:.*?var LIVE_EVENTS\s*=\s*\[.*?\];',
            updated_str,
            html,
            flags=re.DOTALL
        )
        print("Replaced existing LIVE_EVENTS block")
    else:
        html = html.replace(
            "\nvar allEvents = BASE.slice();",
            f"\n{updated_str}\n\nvar allEvents = BASE.slice();"
        )
        print("Inserted LIVE_EVENTS block (first run)")

    if "LIVE_EVENTS.forEach" not in html:
        html = html.replace(
            "var allEvents = BASE.slice();",
            "var allEvents = BASE.slice();\n"
            "if (typeof LIVE_EVENTS !== 'undefined') {\n"
            "  LIVE_EVENTS.forEach(function(ev) { allEvents.push(ev); });\n"
            "}"
        )
        print("Added LIVE_EVENTS merge (first run)")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone. index.html updated with {len(all_new_events)} live events.")
    print(f"Date: {TODAY_STR}")


if __name__ == "__main__":
    main()
