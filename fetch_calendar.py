"""
fetch_calendar.py
Fetches the waste collection calendar from Ville de Saint-Basile-le-Grand
and generates a .ics file for Google Calendar subscription.

Data source: https://www.villesblg.ca/calendrier-categories/collectes-et-depots/
Strategy:
  1. GET the calendar page to extract a fresh nonce
  2. Page through 30-day windows via admin-ajax.php (eventChangeDate action)
  3. Parse event titles + dates from the HTML chunks
  4. Write a valid RFC 5545 ICS file

Window logic:
  - start_date : today - 60 days (catches anything recent)
  - end_date   : Dec 31 of current year
                 If today >= Nov 1, extend to Dec 31 of next year as well
                 (smooth year-end transition, never leaves the calendar empty)
"""

import json
import re
import sys
import uuid
import urllib.request
import urllib.parse
from datetime import date, timedelta
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CALENDAR_URL  = "https://www.villesblg.ca/calendrier-categories/collectes-et-depots/"
AJAX_URL      = "https://www.villesblg.ca/wp-admin/admin-ajax.php"
CATEGORY_ID   = "14"
OUTPUT_FILE   = "collectes-sblg.ics"

# Human-readable descriptions per collection type (French, matches city wording)
DESCRIPTIONS = {
    "Collecte d'ordures ménagères":
        "Bac gris, vert ou noir (à prise européenne). "
        "Placer en bordure de rue après 19h la veille ou avant 7h le jour de la collecte.",
    "Collecte de matières récupérables":
        "Bac bleu. "
        "Placer en bordure de rue après 19h la veille ou avant 7h le jour de la collecte.",
    "Collecte de résidus alimentaires":
        "Bac brun. "
        "Placer en bordure de rue après 19h la veille ou avant 7h le jour de la collecte. "
        "Collecte de 7h à 21h.",
    "Collecte de résidus verts":
        "Sacs de papier, poubelles < 100 L ou bac roulant max 360 L (autocollant MRCVR requis). "
        "Sacs de plastique refusés. Placer après 19h la veille ou avant 7h.",
    "Collecte d'encombrants":
        "Objets volumineux — sur réservation seulement. "
        "Placer en bordure de rue après 19h la veille ou avant 7h le jour de la collecte.",
    "Dépôt de rebuts encombrants et récupérables":
        "Garage municipal Léon-Taillon. Preuve de résidence requise. "
        "Consulter villesblg.ca pour les consignes complètes.",
    "Dépôt de résidus domestiques dangereux (RDD)":
        "Résidus domestiques dangereux. "
        "Consulter villesblg.ca pour les points de collecte et consignes.",
}

DEFAULT_DESCRIPTION = "Consulter villesblg.ca pour les consignes complètes."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str, post_data: dict | None = None) -> str:
    """Simple HTTP GET or POST, returns response body as string."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
    }
    if post_data:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
        data = urllib.parse.urlencode(post_data).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
    else:
        req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_nonce(html: str) -> str:
    """Pull the WordPress nonce from the calendar page HTML."""
    # Embedded in nav link: data-nonce="a9054bca90"
    m = re.search(r'data-nonce=["\']([a-f0-9]+)["\']', html)
    if m:
        return m.group(1)
    # Fallback: look for nonce in inline JS
    m = re.search(r'"nonce"\s*:\s*"([a-f0-9]+)"', html)
    if m:
        return m.group(1)
    raise RuntimeError(
        "Could not find nonce on the calendar page. "
        "The site structure may have changed."
    )


class EventParser(HTMLParser):
    """
    Extracts (date, title) pairs from the HTML chunk returned by the AJAX endpoint.
    Each event is an <article data-date="YYYY-MM-DD"> containing an <h2> title.
    """

    def __init__(self):
        super().__init__()
        self.events: list[tuple[str, str]] = []   # [(date_str, title), ...]
        self._current_date: str | None = None
        self._in_title = False
        self._title_depth = 0
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "article":
            self._current_date = attrs_dict.get("data-date")
        if tag == "h2" and attrs_dict.get("class", "") == "entry-title":
            self._in_title = True
            self._title_depth = 1
            self._buf = ""
        elif self._in_title:
            self._title_depth += 1

    def handle_endtag(self, tag):
        if self._in_title:
            if tag == "h2":
                self._title_depth -= 1
                if self._title_depth <= 0:
                    self._in_title = False
                    title = self._buf.strip()
                    if self._current_date and title:
                        self.events.append((self._current_date, title))
                    self._buf = ""
            else:
                self._title_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self._buf += data


def parse_events_from_ajax(html_chunk: str) -> list[tuple[str, str]]:
    parser = EventParser()
    parser.feed(html_chunk)
    return parser.events


def compute_date_window() -> tuple[date, date]:
    today = date.today()
    start = today - timedelta(days=60)
    # Default end: Dec 31 of current year
    end = date(today.year, 12, 31)
    # From Nov 1 onward, also pull next year so the calendar never looks empty
    if today.month >= 11:
        end = date(today.year + 1, 12, 31)
    return start, end


def date_to_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def ics_escape(text: str) -> str:
    """Escape special characters for ICS text fields."""
    return (
        text
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """
    RFC 5545 line folding: lines > 75 octets must be folded
    with CRLF + space continuation.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line + "\r\n"
    result = []
    chunk_start = 0
    first = True
    while chunk_start < len(encoded):
        max_bytes = 75 if first else 74   # 74 because continuation adds 1 space byte
        chunk = encoded[chunk_start: chunk_start + max_bytes]
        # Don't split a multi-byte character
        while len(chunk) > 0:
            try:
                chunk.decode("utf-8")
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        result.append((" " if not first else "") + chunk.decode("utf-8"))
        chunk_start += len(chunk)
        first = False
    return "\r\n".join(result) + "\r\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch_all_events(start: date, end: date) -> list[tuple[str, str]]:
    """
    Pages through 30-day windows from start to end,
    collecting (date_str, title) tuples.
    """
    print("Fetching calendar page to get nonce...", flush=True)
    page_html = fetch_url(CALENDAR_URL)
    nonce = extract_nonce(page_html)
    print(f"Nonce: {nonce}", flush=True)

    all_events: dict[tuple[str, str], None] = {}   # ordered dedup
    current = start - timedelta(days=1)  # -1 so first window includes events on start itself
    window_count = 0

    while current <= end:
        window_count += 1
        date_str = current.strftime("%Y-%m-%d")
        print(f"  Fetching window {window_count}: {date_str} ...", end=" ", flush=True)

        payload = {
            "action":  "eventChangeDate",
            "date":    date_str,
            "trigger": "next",
            "nonce":   nonce,
            "cat":     CATEGORY_ID,
        }

        try:
            resp = fetch_url(AJAX_URL, post_data=payload)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            # Try to continue with next window rather than abort
            current += timedelta(days=30)
            continue

        # Parse the JSON response properly — handles all escape sequences
        # including the \/ WordPress uses in URLs.
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}", flush=True)
            current += timedelta(days=30)
            continue

        html_chunk = data.get("events_loop_content", "")
        date_last_str = data.get("date_last", "")

        if not html_chunk:
            print("no events_loop_content — end of data?", flush=True)
            break

        events = parse_events_from_ajax(html_chunk)
        print(f"{len(events)} events found", flush=True)

        for ev in events:
            all_events[ev] = None

        # Advance by reading date_last from the response
        if date_last_str and len(date_last_str) == 8:
            dl = date_last_str   # YYYYMMDD
            next_date = date(int(dl[:4]), int(dl[4:6]), int(dl[6:]))  # no +1: AJAX window is (date, date+30], so pass date_last directly
        else:
            next_date = current + timedelta(days=30)

        if next_date <= current:
            # Sanity guard against infinite loop
            next_date = current + timedelta(days=30)

        current = next_date

    return list(all_events.keys())


def build_ics(events: list[tuple[str, str]]) -> str:
    """Builds the ICS file content from a list of (date_str, title) tuples."""
    import datetime
    now_stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR\r\n",
        "VERSION:2.0\r\n",
        "PRODID:-//Collectes SBLG//FR\r\n",
        "CALSCALE:GREGORIAN\r\n",
        "METHOD:PUBLISH\r\n",
        fold_line("X-WR-CALNAME:Collectes et dépôts — Saint-Basile-le-Grand"),
        "X-WR-TIMEZONE:America/Toronto\r\n",
        fold_line(
            "X-WR-CALDESC:Calendrier des collectes et dépôts de la "
            "Ville de Saint-Basile-le-Grand. "
            "Source: villesblg.ca"
        ),
    ]

    # Sort by date then title for a deterministic file (avoids spurious git diffs)
    sorted_events = sorted(events, key=lambda x: (x[0], x[1]))

    for date_str, title in sorted_events:
        # date_str from the AJAX is YYYY-MM-DD
        d = date_str.replace("-", "")

        description = DESCRIPTIONS.get(title, DEFAULT_DESCRIPTION)
        uid = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"sblg-{date_str}-{title}"
        ))

        lines += [
            "BEGIN:VEVENT\r\n",
            fold_line(f"UID:{uid}"),
            fold_line(f"DTSTAMP:{now_stamp}"),
            fold_line(f"DTSTART;VALUE=DATE:{d}"),
            fold_line(f"DTEND;VALUE=DATE:{d}"),
            fold_line(f"SUMMARY:{ics_escape(title)}"),
            fold_line(f"DESCRIPTION:{ics_escape(description)}"),
            "TRANSP:TRANSPARENT\r\n",
            "END:VEVENT\r\n",
        ]

    lines.append("END:VCALENDAR\r\n")
    return "".join(lines)


def main():
    start, end = compute_date_window()
    print(f"Date window: {start} → {end}", flush=True)

    events = fetch_all_events(start, end)
    print(f"\nTotal unique events collected: {len(events)}", flush=True)

    if not events:
        print("No events found. Check nonce extraction or site availability.", file=sys.stderr)
        sys.exit(1)

    ics_content = build_ics(events)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(ics_content)

    print(f"Written: {OUTPUT_FILE} ({len(ics_content)} bytes, {len(events)} events)")


if __name__ == "__main__":
    main()
