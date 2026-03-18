import csv
import sys
import time
import requests
from datetime import datetime, timedelta

# ── Config ──────────────────────────────────────────────────────────────────

CSV_PATH       = sys.argv[1] if len(sys.argv) > 1 else "pydata_groups.csv"
WORLD_CITIES   = "worldcities.csv"
DELAY          = 0.01
TIMEOUT        = 10

# ── Candidate cities to probe ────────────────────────────────────────────────

def load_candidate_cities(csv_path: str) -> tuple[list[dict], list[str]]:
    """Returns (all_rows, city_names_ascii, fieldnames)."""
    rows   = []
    cities = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader     = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
            cities.append(row["city_ascii"].lower().strip())
    return rows, cities, fieldnames

# ── Load known groups from CSV ───────────────────────────────────────────────

def load_known(csv_path: str):
    known_urlnames = set()
    known_cities   = set()
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                known_urlnames.add(row["urlname"].lower().strip())
                known_cities.add(row["city"].lower().strip())
                q = row.get("query", "").lower().strip()
                if q:
                    known_cities.add(q.split(",")[0].strip())
    except FileNotFoundError:
        print(f"WARNING: CSV not found at {csv_path}. Proceeding without exclusions.")
    return known_urlnames, known_cities

# ── Slug generation ──────────────────────────────────────────────────────────

def city_to_slugs(city: str) -> list[str]:
    base      = city.lower().replace(" ", "-")
    condensed = base.replace("-", "")
    return [
        f"pydata-{base}",
        f"PyData-{base}",
        f"pydata{condensed}",
    ]

# ── HTTP probe ───────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return s

def check_slug(session: requests.Session, slug: str) -> tuple[bool, str]:
    url = f"https://www.meetup.com/{slug}/"
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            not_found_signals = [
                "group not found",
                "sorry, the group you're looking for doesn't exist",
                "doesn't exist",
            ]
            if any(s in r.text.lower() for s in not_found_signals):
                return False, r.url
            return True, r.url
        return False, r.url
    except requests.RequestException:
        return False, ""

# ── Progress bar ─────────────────────────────────────────────────────────────

def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"

def print_progress(done: int, total: int, found: int, start_time: float):
    width    = 30
    filled   = int(width * done / total) if total else 0
    bar      = "█" * filled + "░" * (width - filled)
    pct      = 100 * done / total if total else 0

    elapsed  = time.time() - start_time
    if done > 0:
        rate      = done / elapsed                    # cities per second
        remaining = (total - done) / rate
        eta       = datetime.now() + timedelta(seconds=remaining)
        time_str  = f"  ETA {eta.strftime('%H:%M:%S')}  ({fmt_duration(remaining)} left)"
    else:
        time_str  = ""

    print(f"\r  [{bar}] {pct:5.1f}%  {done}/{total}  |  ✅ {found}{time_str}",
          end="", flush=True)

# ── Rewrite worldcities.csv removing tested rows ─────────────────────────────

def remove_tested_cities(csv_path: str, all_rows: list[dict],
                          fieldnames: list[str], tested: set[str]):
    remaining = [r for r in all_rows
                 if r["city_ascii"].lower().strip() not in tested]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(remaining)
    return len(all_rows) - len(remaining)

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading known groups from: {CSV_PATH}")
    known_urlnames, known_cities = load_known(CSV_PATH)
    print(f"  Known urlnames : {len(known_urlnames)}")
    print(f"  Known cities   : {len(known_cities)}")

    all_rows, candidate_cities, fieldnames = load_candidate_cities(WORLD_CITIES)

    to_probe = [
        c for c in candidate_cities
        if c.replace("-", " ") not in known_cities and c not in known_cities
    ]

    skipped = len(candidate_cities) - len(to_probe)
    print(f"\nProbing {len(to_probe)} cities (skipping {skipped} already present)...\n")

    session    = make_session()
    found      = []
    tested     = set()
    start_time = time.time()

    out = "potential_missing_groups.txt"
    with open(out, "w", buffering=1) as outfile:
        outfile.write("city\tslug\turl\n")

        for i, city in enumerate(to_probe):
            print_progress(i, len(to_probe), len(found), start_time)

            slugs = city_to_slugs(city)
            for slug in slugs:
                if slug.lower() in known_urlnames:
                    continue
                exists, final_url = check_slug(session, slug)
                if exists:
                    print(f"\r  ✅  FOUND  {city:28s} → {final_url}")
                    found.append((city, slug, final_url))
                    outfile.write(f"{city}\t{slug}\t{final_url}\n")
                    break
                time.sleep(DELAY)

            tested.add(city)

            # Checkpoint: rewrite worldcities.csv every 500 cities
            if len(tested) % 500 == 0:
                remove_tested_cities(WORLD_CITIES, all_rows, fieldnames, tested)

        print_progress(len(to_probe), len(to_probe), len(found), start_time)
        print()  # newline after final progress bar

    # Final rewrite — remove everything tested this run
    removed = remove_tested_cities(WORLD_CITIES, all_rows, fieldnames, tested)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"Done in {fmt_duration(elapsed)}. Probed {len(tested)} cities, removed {removed} from {WORLD_CITIES}.")
    print(f"Found {len(found)} potential missing group(s):\n")
    for city, slug, url in found:
        print(f"  {city:30s}  {url}")
    print(f"\nResults saved to: {out}")

if __name__ == "__main__":
    main()