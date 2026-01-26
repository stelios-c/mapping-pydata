import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _():
    import re
    import folium
    import marimo as mo
    import requests
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    import json
    from pathlib import Path
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter

    import marimo as mo
    import pandas as pd
    import asyncio

    import shutil
    import math
    from pathlib import Path
    return (
        Nominatim,
        Path,
        RateLimiter,
        async_playwright,
        folium,
        json,
        math,
        mo,
        pd,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Meetup is horrendus, I don't like their API. I want to go round to Meetup's house and bend all their spoons.

    Here's a janky script to extract a complete list of PyData groups from https://www.meetup.com/pro/pydata/
    """)
    return


@app.cell
async def _(async_playwright, json):
    async def get_pydata_groups():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            await page.goto('https://www.meetup.com/pro/pydata/')
            await page.wait_for_selector('[data-testid="group"]')

            # Scroll and collect in browser context
            groups = await page.evaluate('''
                async () => {
                    const allGroups = new Map();
                    let lastCount = 0;
                    let stableCount = 0;

                    while (stableCount < 5) {
                        document.querySelectorAll('[data-testid="group"]').forEach(el => {
                            const link = el.querySelector('a');
                            const url = link?.href || '';
                            if (url && !allGroups.has(url)) {
                                const text = el.innerText;

                                // Extract member count
                                const memberMatch = text.match(/([\\d,]+)\\s*members?/i);

                                // Extract rating (e.g., "4.7")
                                const ratingMatch = text.match(/^([\\d.]+)$/m);

                                // First line often has "City, NN" where NN is number of events
                                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                                const firstLine = lines[0] || '';
                                const locationMatch = firstLine.match(/^([^,]+),\\s*(\\d+)$/);

                                // Clean the URL (remove tracking params)
                                const cleanUrl = url.split('?')[0];

                                allGroups.set(cleanUrl, {
                                    name: el.querySelector('h3')?.textContent?.trim() || '',
                                    url: cleanUrl,
                                    urlname: cleanUrl.match(/meetup\\.com\\/([^\\/]+)/)?.[1] || '',
                                    members: memberMatch ? parseInt(memberMatch[1].replace(/,/g, '')) : null,
                                    city: locationMatch ? locationMatch[1] : firstLine.split(',')[0],
                                    rating: ratingMatch ? parseFloat(ratingMatch[1]) : null,
                                });
                            }
                        });

                        window.scrollTo(0, document.body.scrollHeight);
                        await new Promise(r => setTimeout(r, 2000));

                        if (allGroups.size === lastCount) stableCount++;
                        else stableCount = 0;
                        lastCount = allGroups.size;
                    }
                    return Array.from(allGroups.values());
                }
            ''')
            await browser.close()
        return groups

    groups = await get_pydata_groups()
    print(f"Found {len(groups)} groups")
    if groups:
        print("\nSample card data:")
        print(json.dumps(groups[0], indent=2))
    return (groups,)


@app.cell
def _(groups, pd):
    df = pd.DataFrame(groups)
    df
    return


@app.cell
def _(Nominatim, Path, RateLimiter, groups, json):
    CACHE_FILE = Path("geocode_cache.json")

    def load_cache():
        """Load existing cache or return default structure"""
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                return json.load(f)
        return {
            "hints": {},      # name -> geocode query (or null to skip)
            "coords": {}      # query -> {lat, lon, display_name}
        }

    def save_cache(cache):
        """Save cache to file"""
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)

    def get_query_for_group(name, cache):
        """Get the geocoding query for a group name"""
        # Check cache hints first (user overrides)
        if name in cache['hints']:
            return cache['hints'][name]
        # Default: strip common prefixes/suffixes
        return name.replace('PyData ', '').replace(' Meetup', '').replace(' Group', '').replace('PyData', '')

    def geocode_groups(groups):
        """Geocode groups with caching"""
        cache = load_cache()

        geolocator = Nominatim(user_agent="pydata_mapper", timeout=10)
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.5)

        results = []
        cache_hits = 0
        api_calls = 0

        for group in groups:
            name = group['name']
            query = get_query_for_group(name, cache)

            # Skip if marked as None
            if query is None:
                print(f"⊘ {name} (skipped)")
                continue

            # Check coordinate cache
            if query in cache['coords']:
                cached = cache['coords'][query]
                results.append({
                    **group,
                    'query': query,
                    'lat': cached['lat'],
                    'lon': cached['lon']
                })
                print(f"✓ {name} -> {query} ({cached['lat']:.2f}, {cached['lon']:.2f}) [cached]")
                cache_hits += 1
                continue

            # Call Nominatim
            try:
                location = geocode(query)
                if location:
                    cache['coords'][query] = {
                        'lat': location.latitude,
                        'lon': location.longitude,
                        'display_name': location.address
                    }
                    results.append({
                        **group,
                        'query': query,
                        'lat': location.latitude,
                        'lon': location.longitude
                    })
                    print(f"✓ {name} -> {query} ({location.latitude:.2f}, {location.longitude:.2f})")
                    api_calls += 1
                else:
                    print(f"✗ {name} -> {query} (not found)")
            except Exception as e:
                print(f"✗ {name} -> {query} (error: {type(e).__name__})")

        # Save updated cache
        save_cache(cache)

        print(f"\nGeocoded {len(results)} of {len(groups)} groups")
        print(f"Cache hits: {cache_hits}, API calls: {api_calls}")

        return results

    # Run geocoding
    groups_with_coords = geocode_groups(groups)
    return groups_with_coords, load_cache


@app.cell
def _(groups_with_coords, load_cache, pd):
    # =============================================================================
    # CELL: Add country field from geocode cache
    # =============================================================================

    cache = load_cache()

    def get_country_from_cache(query):
        """Extract country from cached display_name (last part of address)"""
        if query in cache['coords']:
            display_name = cache['coords'][query].get('display_name', '')
            # Country is typically the last part after the final comma
            parts = display_name.split(', ')
            if parts:
                return parts[-1].strip()
        return None

    # Add country to groups_with_coords
    for _g in groups_with_coords:
        _g['country'] = get_country_from_cache(_g.get('query', ''))

    # Recreate DataFrame
    df_geo = pd.DataFrame(groups_with_coords)

    df_geo['country'].value_counts()
    return


@app.cell
def _(folium, groups_with_coords):
    # Create the map centered on Europe (where most PyData groups are)
    _m = folium.Map(location=[30, 0], zoom_start=2)

    # Add markers for each group
    for _g in groups_with_coords:
        folium.CircleMarker(
            location=[_g['lat'], _g['lon']],
            radius=8,
            popup=f"<a href='{_g['url']}' target='_blank'>{_g['name']}</a>",
            tooltip=_g['name'],
            color='#ee9041',
            fill=True,
            fill_color='#ee9041',
            fill_opacity=0.7
        ).add_to(_m)
    _m.save('pydata_world_map.html')
    _m
    return


@app.cell
def _(folium, groups_with_coords):
    # UK bounding box (approximate)
    UK_BOUNDS = {
        'min_lat': 49.5,   # South coast
        'max_lat': 61.0,   # Shetland
        'min_lon': -8.5,   # Western Ireland/Scotland
        'max_lon': 2.0     # East coast
    }

    def is_in_uk(lat, lon):
        return (UK_BOUNDS['min_lat'] <= lat <= UK_BOUNDS['max_lat'] and 
                UK_BOUNDS['min_lon'] <= lon <= UK_BOUNDS['max_lon'])

    # Filter to UK groups using coordinates
    uk_groups = [_g for _g in groups_with_coords if is_in_uk(_g['lat'], _g['lon'])]
    print(f"Found {len(uk_groups)} UK groups:")
    for _g in uk_groups:
        print(f"  {_g['name']}")

    # Create UK-centered map
    _m = folium.Map(location=[54.5, -2], zoom_start=6)

    for _g in uk_groups:
        folium.CircleMarker(
            location=[_g['lat'], _g['lon']],
            radius=10,
            popup=f"<a href='{_g['url']}' target='_blank'>{_g['name']}</a>",
            tooltip=_g['name'],
            color='#ee9041',
            fill=True,
            fill_color='#ee9041',
            fill_opacity=0.7
        ).add_to(_m)

    _m
    return (uk_groups,)


@app.cell
async def _(async_playwright, pd, uk_groups):
    # =============================================================================
    # CELL: Enrich UK groups with public details
    # =============================================================================
    from datetime import datetime, timezone

    async def get_group_details_public(group_url):
        """Get public data from main group page - no login required"""

        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})

            await page.goto(group_url, wait_until='networkidle', timeout=30000)

            details = await page.evaluate('''
                () => {
                    const text = document.body.innerText;

                    // Past events count
                    const pastMatch = text.match(/Past events\\s*(\\d+)/);
                    const pastEventsCount = pastMatch ? parseInt(pastMatch[1]) : 0;

                    // Organizer count from "and X others"
                    const organizerMatch = text.match(/and (\\d+) others/);
                    let organizerCount = organizerMatch ? parseInt(organizerMatch[1]) + 1 : null;

                    // Get visible organizer name
                    const organizerLink = document.querySelector('a[href*="/members/?op=leaders"]');
                    const primaryOrganizer = organizerLink?.previousElementSibling?.innerText?.trim() || 
                                             organizerLink?.parentElement?.querySelector('img')?.alt?.replace('Photo of the user ', '') ||
                                             null;

                    // Only look for last event date if there are past events
                    let lastEventDate = null;
                    if (pastEventsCount > 0) {
                        // Approach 1: Find time element near past events
                        const allTimeElements = document.querySelectorAll('time[datetime]');
                        for (const timeEl of allTimeElements) {
                            const parent = timeEl.closest('a[href*="/events/"]');
                            if (parent && parent.href.includes('eventOrigin=group_past_events')) {
                                lastEventDate = timeEl.getAttribute('datetime');
                                break;
                            }
                        }

                        // Approach 2: Look for past events section and get first date
                        if (!lastEventDate) {
                            const pastSection = document.evaluate(
                                "//h2[contains(text(), 'Past events')]/following::time[@datetime][1]",
                                document,
                                null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE,
                                null
                            ).singleNodeValue;
                            if (pastSection) {
                                lastEventDate = pastSection.getAttribute('datetime');
                            }
                        }

                        // Approach 3: Get all event cards and find ones with past dates
                        if (!lastEventDate) {
                            const now = new Date();
                            allTimeElements.forEach(timeEl => {
                                if (!lastEventDate) {
                                    const dt = timeEl.getAttribute('datetime');
                                    if (dt) {
                                        const eventDate = new Date(dt.split('[')[0]);
                                        if (eventDate < now) {
                                            lastEventDate = dt;
                                        }
                                    }
                                }
                            });
                        }
                    }

                    // Check for upcoming events - must have actual event cards, not just the section header
                    const upcomingEventCards = document.querySelectorAll('a[href*="eventOrigin=group_upcoming_events"]');
                    const hasUpcoming = upcomingEventCards.length > 0;

                    return {
                        past_events_count: pastEventsCount,
                        organizer_count: organizerCount,
                        primary_organizer: primaryOrganizer,
                        last_event_date: lastEventDate,
                        has_upcoming_events: hasUpcoming
                    };
                }
            ''')

            await browser.close()

            # Add URLs
            base = group_url.rstrip('/')
            details['events_url'] = f"{base}/events/"
            details['leaders_url'] = f"{base}/members/?op=leaders"

            # Calculate days since last event - only if we have past events AND a date
            if details.get('past_events_count', 0) > 0 and details.get('last_event_date'):
                try:
                    date_str = details['last_event_date'].split('[')[0]
                    last_event = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    details['days_since_last_event'] = (now - last_event).days
                except:
                    details['days_since_last_event'] = None
            else:
                details['days_since_last_event'] = None

            return details

    print(f"Enriching {len(uk_groups)} UK groups...\n")

    uk_groups_enriched = []
    for i, group in enumerate(uk_groups):
        print(f"[{i+1}/{len(uk_groups)}] {group['name']}...", end=' ')

        try:
            details = await get_group_details_public(group['url'] + '/')
            enriched = {**group, **details}
            uk_groups_enriched.append(enriched)

            days = details.get('days_since_last_event')
            days_str = f"{days} days ago" if days is not None else "never"
            upcoming = "✓" if details.get('has_upcoming_events') else "✗"
            print(f"✓ {details.get('past_events_count', 0) or 0} events, last: {days_str}, upcoming: {upcoming}")
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")
            uk_groups_enriched.append(group)

    print("\n" + "="*60)
    print(f"Enriched {len(uk_groups_enriched)} UK groups")

    # Create DataFrame
    df_uk = pd.DataFrame(uk_groups_enriched)

    # Reorder columns for readability
    cols = ['name', 'city', 'members', 'past_events_count', 'days_since_last_event', 
            'has_upcoming_events', 'organizer_count', 'events_url', 'leaders_url', 'lat', 'lon']
    cols = [c for c in cols if c in df_uk.columns]
    df_uk = df_uk[cols]

    df_uk
    return get_group_details_public, uk_groups_enriched


@app.cell
def _(folium, math, uk_groups_enriched):
    # =============================================================================
    # CELL: UK map with activity-based styling
    # =============================================================================

    def get_marker_style(group):
        """Calculate fill color and opacity based on activity"""

        # Color: green if upcoming events
        if group.get('has_upcoming_events'):
            fill_color = '#22c55e'  # green
            fill_opacity = 0.9
        else:
            fill_color = '#0000FF'

            # Opacity: logarithmic scale - drops quickly then levels off
            days = group.get('days_since_last_event')
            if days is None:
                fill_opacity = 0.1  # No data - very transparent
            else:
                fill_opacity = max(0.4, 0.9 - (math.log1p(days) / math.log1p(365)))

        return fill_color, fill_opacity


    # Create UK map
    _m = folium.Map(location=[54.5, -2], zoom_start=6)

    for _g in uk_groups_enriched:
        fill_color, fill_opacity = get_marker_style(_g)

        # Build popup with details
        _days = _g.get('days_since_last_event')
        _members = _g.get('members')
        _days_str = f"{_days} days ago" if _days is not None else "Never"
        _upcoming_str = "Yes ✓" if _g.get('has_upcoming_events') else "No"

        popup_html = f"""
            <b><a href='{_g['url']}' target='_blank'>{_g['name']}</a></b><br>
            📍 {_g.get('city', 'Unknown')}<br>
            👥 {_g.get('members', '?')} members<br>
            📅 {_g.get('past_events_count', 0)} past events<br>
            ⏱️ Last event: {_days_str}<br>
            🔜 Upcoming: {_upcoming_str}<br>
            <a href='{_g.get('events_url', '')}' target='_blank'>Events</a> |
            <a href='{_g.get('leaders_url', '')}' target='_blank'>Leaders</a>
        """

        _radius = max(5, math.log(_members) * 2)

        folium.CircleMarker(
            location=[_g['lat'], _g['lon']],
            radius=_radius,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{_g['name']} ({_g.get('members', '?')} members)",
            color=fill_color,
            fill=True,
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            weight=0
        ).add_to(_m)

    _m
    return (get_marker_style,)


@app.cell
async def _(get_group_details_public, groups_with_coords, pd):
    # =============================================================================
    # CELL: Enrich ALL groups with public details
    # =============================================================================

    print(f"Enriching {len(groups_with_coords)} groups worldwide...\n")

    all_groups_enriched = []
    for _i, _group in enumerate(groups_with_coords):
        print(f"[{_i+1}/{len(groups_with_coords)}] {_group['name']}...", end=' ')

        try:
            _details = await get_group_details_public(_group['url'] + '/')
            _enriched = {**_group, **_details}
            all_groups_enriched.append(_enriched)

            _days = _details.get('days_since_last_event')
            _days_str = f"{_days} days ago" if _days is not None else "never"
            _upcoming = "✓" if _details.get('has_upcoming_events') else "✗"
            print(f"✓ {_details.get('past_events_count', 0) or 0} events, last: {_days_str}, upcoming: {_upcoming}")
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")
            all_groups_enriched.append(_group)

    print("\n" + "="*60)
    print(f"Enriched {len(all_groups_enriched)} groups")

    # Create DataFrame
    df_all = pd.DataFrame(all_groups_enriched)
    df_all
    return all_groups_enriched, df_all


@app.cell
def _(all_groups_enriched, df_all, folium, get_marker_style, math):
    df_all.sort_values(by=['members'], ascending=True)
    # Create world map
    world_map = folium.Map(location=[30, 0], zoom_start=2)

    for _g in all_groups_enriched:
        if 'lat' not in _g or 'lon' not in _g:
            continue

        _fill_color, _fill_opacity = get_marker_style(_g)

        _days = _g.get('days_since_last_event')
        _days_str = f"{_days} days ago" if _days is not None else "Never"
        _upcoming_str = "Yes ✓" if _g.get('has_upcoming_events') else "No"

        _popup_html = f"""
            <b><a href='{_g['url']}' target='_blank'>{_g['name']}</a></b><br>
            📍 {_g.get('city', 'Unknown')}<br>
            👥 {_g.get('members', '?')} members<br>
            📅 {_g.get('past_events_count', 0) or 0} past events<br>
            ⏱️ Last event: {_days_str}<br>
            🔜 Upcoming: {_upcoming_str}<br>
            <a href='{_g.get('events_url', '')}' target='_blank'>Events</a> |
            <a href='{_g.get('leaders_url', '')}' target='_blank'>Leaders</a>
        """

        _members = _g.get('members') or 10
        _radius = max(5, math.log(_members) * 2)

        folium.CircleMarker(
            location=[_g['lat'], _g['lon']],
            radius=_radius,
            popup=folium.Popup(_popup_html, max_width=300),
            tooltip=f"{_g['name']} ({_members} members)",
            color=_fill_color,
            fill=True,
            fill_color=_fill_color,
            fill_opacity=_fill_opacity,
            weight=0
        ).add_to(world_map)

    world_map.save('pydata_world_map_layers.html')
    world_map
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
