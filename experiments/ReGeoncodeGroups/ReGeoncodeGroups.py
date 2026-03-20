"""
regeocodeall.py
===============
Force re-geocodes every group in pydata_groups.csv using city + country
columns directly. Manual hints in geocode_cache.json["hints"] take priority.

Usage:
    python regeocodeall.py [path/to/pydata_groups.csv] [--failed-only]

    --failed-only   Only attempt groups with missing lat/lon in the CSV.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pycountry
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

args        = [a for a in sys.argv[1:] if not a.startswith("--")]
flags       = [a for a in sys.argv[1:] if a.startswith("--")]
CSV_PATH    = args[0] if args else "pydata_groups.csv"
FAILED_ONLY = "--failed-only" in flags
CACHE_FILE  = Path("geocode_cache.json")


def normalise_country(name: str) -> str:
    """Return the English country name for a native-language or alternate name."""
    if not name:
        return name
    name = name.strip()

    # Try exact match first (handles ISO codes, English names, many native names)
    try:
        return pycountry.countries.lookup(name).name
    except LookupError:
        pass

    # Try searching common_name and official_name fields
    for country in pycountry.countries:
        if name.lower() in (
            getattr(country, "common_name", "").lower(),
            getattr(country, "official_name", "").lower(),
        ):
            return country.name

    # If all else fails, return original
    return name


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {"hints": {}, "coords": {}}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def main():
    df = pd.read_csv(CSV_PATH)

    # Normalise country names before geocoding
    if "country" in df.columns:
        df["country"] = df["country"].apply(
            lambda x: normalise_country(x) if pd.notna(x) else x
        )

    print(f"Loaded {len(df)} groups from {CSV_PATH}")

    if FAILED_ONLY:
        missing_mask = df["lat"].isna() | df["lon"].isna()
        to_geocode   = df[missing_mask].index.tolist()
        print(f"Mode: --failed-only ({len(to_geocode)} groups with missing coordinates)\n")
    else:
        to_geocode = df.index.tolist()
        print(f"Mode: all ({len(to_geocode)} groups)\n")

    if not to_geocode:
        print("Nothing to geocode.")
        return

    cache = load_cache()
    hints = cache.get("hints", {})

    geolocator = Nominatim(user_agent="pydata_mapper_regeocoder", timeout=10)
    geocode    = RateLimiter(geolocator.geocode, min_delay_seconds=1.5)

    success = 0
    failed  = 0

    for i in to_geocode:
        row     = df.loc[i]
        name    = row["name"]
        city    = str(row.get("city", "") or "").strip()
        country = str(row.get("country", "") or "").strip()

        # Priority: manual hint > city+country > city alone
        if name in hints:
            query  = hints[name]
            source = "hint"
        elif city and country:
            query  = f"{city}, {country}"
            source = "city+country"
        elif city:
            query  = city
            source = "city"
        else:
            print(f"  ⊘  {name} (no city or hint — skipping)")
            continue

        try:
            location = geocode(query)
            if location:
                # Extract and normalise country from Nominatim display_name
                parts       = location.address.split(", ")
                raw_country = parts[-1].strip() if parts else ""
                normalised  = normalise_country(raw_country)

                cache["coords"][query] = {
                    "lat":          location.latitude,
                    "lon":          location.longitude,
                    "display_name": location.address,
                }
                df.at[i, "lat"]     = location.latitude
                df.at[i, "lon"]     = location.longitude
                df.at[i, "query"]   = query
                df.at[i, "country"] = normalised
                print(f"  ✅  {name}  →  {query} [{source}]  ({location.latitude:.4f}, {location.longitude:.4f})  [{normalised}]")
                success += 1
            else:
                print(f"  ✗   {name}  →  {query} [{source}]  (not found — add a hint to geocode_cache.json)")
                failed += 1
        except Exception as e:
            print(f"  ✗   {name}  →  {query}  (error: {type(e).__name__}: {e})")
            failed += 1

        # Save after every group so ctrl-C doesn't lose progress
        save_cache(cache)

    df.to_csv(CSV_PATH, index=False)
    print(f"\nDone. {success} updated, {failed} failed.")
    print(f"Cache saved to {CACHE_FILE}, CSV updated at {CSV_PATH}")
    if failed:
        print(f"\nTo fix failures, add entries to geocode_cache.json like:")
        print(f'  "hints": {{ "Group Name": "City, Country" }}')


if __name__ == "__main__":
    main()