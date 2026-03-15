# PyDataMap.py
import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import folium
from folium.plugins import MarkerCluster
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from playwright.async_api import async_playwright

CACHE_FILE = Path("geocode_cache.json")

ESRI_TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'
ESRI_ATTR = 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012'

def get_cached_pydata_groups():
    if Path("pydata_groups.csv").exists():
        df = pd.read_csv("pydata_groups.csv")
        return df.to_dict(orient='records')
    return None

# Scrape all PyData groups from meetup.com/pro/pydata
async def get_pydata_groups():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 800})
        await page.goto('https://www.meetup.com/pro/pydata/')
        await page.wait_for_selector('[data-testid="group"]')

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
                            const memberMatch = text.match(/([\\d,]+)\\s*members?/i);
                            const ratingMatch = text.match(/^([\\d.]+)$/m);
                            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                            const firstLine = lines[0] || '';
                            const locationMatch = firstLine.match(/^([^,]+),\\s*(\\d+)$/);
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

# Get public data from main group page - no login required
async def get_group_details_public(page, group_url):
    await page.goto(group_url, wait_until='networkidle', timeout=30000)

    details = await page.evaluate('''
        () => {
            const text = document.body.innerText;

            const pastMatch = text.match(/Past events\\s*(\\d+)/);
            const pastEventsCount = pastMatch ? parseInt(pastMatch[1]) : 0;

            const organizerMatch = text.match(/and (\\d+) others/);
            let organizerCount = organizerMatch ? parseInt(organizerMatch[1]) + 1 : null;

            const organizerLink = document.querySelector('a[href*="/members/?op=leaders"]');
            const primaryOrganizer = organizerLink?.previousElementSibling?.innerText?.trim() || 
                                     organizerLink?.parentElement?.querySelector('img')?.alt?.replace('Photo of the user ', '') ||
                                     null;

            let lastEventDate = null;
            if (pastEventsCount > 0) {
                const allTimeElements = document.querySelectorAll('time[datetime]');
                for (const timeEl of allTimeElements) {
                    const parent = timeEl.closest('a[href*="/events/"]');
                    if (parent && parent.href.includes('eventOrigin=group_past_events')) {
                        lastEventDate = timeEl.getAttribute('datetime');
                        break;
                    }
                }

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

    base = group_url.rstrip('/')
    details['events_url'] = f"{base}/events/"
    details['leaders_url'] = f"{base}/members/?op=leaders"

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

# Load existing cache or return default structure
def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {
        "hints": {},
        "coords": {}
    }

# Save cache to file
def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

# Get the geocoding query for a group name
def get_query_for_group(name, cache):
    if name in cache['hints']:
        return cache['hints'][name]
    return name.replace('PyData ', '').replace(' Meetup', '').replace(' Group', '').replace('PyData', '')

# Geocode groups with caching
def geocode_groups(groups):
    cache = load_cache()

    geolocator = Nominatim(user_agent="pydata_mapper", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.5)

    results = []
    cache_hits = 0
    api_calls = 0

    for group in groups:
        name = group['name']
        query = get_query_for_group(name, cache)

        if query is None:
            print(f"⊘ {name} (skipped)")
            continue

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

    save_cache(cache)

    print(f"\nGeocoded {len(results)} of {len(groups)} groups")
    print(f"Cache hits: {cache_hits}, API calls: {api_calls}")

    return results

# Extract country from cached display_name
def get_country_from_cache(query):
    cache = load_cache()
    if query in cache['coords']:
        display_name = cache['coords'][query].get('display_name', '')
        parts = display_name.split(', ')
        if parts:
            return parts[-1].strip()
    return None

# Calculate fill color and opacity for layers map (green/blue active styling)
def get_marker_style_layers(group):
    if group.get('has_upcoming_events'):
        fill_color = '#22c55e'  # green
        fill_opacity = 0.9
    else:
        fill_color = '#0000FF'  # blue
        days = group.get('days_since_last_event')
        if days is None:
            fill_opacity = 0.1
        else:
            fill_opacity = max(0.4, 0.9 - (math.log1p(days) / math.log1p(365)))
    return fill_color, fill_opacity

# Calculate fill color and opacity for inactive map (red inactive, faint blue active)
def get_marker_style_inactive(group):
    days = group.get('days_since_last_event')
    if group.get('has_upcoming_events') or (days is not None and days < 100):
        fill_color = '#0000FF'  # blue
        fill_opacity = 0.1
    else:
        fill_color = '#FF0000'  # red
        if days is None:
            fill_opacity = 0.9  # Never had events - bright red
        else:
            fill_opacity = min(0.9, 0.1 + (math.log1p(days) / math.log1p(365)) * 0.8)
    return fill_color, fill_opacity

# Build popup HTML for a group
def build_popup_html(g):
    days = g.get('days_since_last_event')
    days_str = f"{days} days ago" if days is not None else "Never"
    upcoming_str = "Yes ✓" if g.get('has_upcoming_events') else "No"
    past_count = g.get('past_events_count', 0) or 0

    return f"""
        <b><a href='{g['url']}' target='_blank'>{g['name']}</a></b><br>
        📍 {g.get('city', 'Unknown')}<br>
        👥 {g.get('members', '?')} members<br>
        📅 {past_count} past events<br>
        ⏱️ Last event: {days_str}<br>
        🔜 Upcoming: {upcoming_str}<br>
        <a href='{g.get('events_url', '')}' target='_blank'>Events</a> |
        <a href='{g.get('leaders_url', '')}' target='_blank'>Leaders</a>
    """

# Round coords to group nearby markers (2 decimal places ≈ 1km)
def coord_key(lat, lon, precision=2):
    return (round(lat, precision), round(lon, precision))

# Create a circle marker for a group
def create_marker(g, style='orange'):
    members = g.get('members') or 10

    if style == 'layers':
        fill_color, fill_opacity = get_marker_style_layers(g)
        radius = max(5, math.log(members) * 2)
        popup = folium.Popup(build_popup_html(g), max_width=300)
        tooltip = f"{g['name']} ({members} members)"
    elif style == 'inactive':
        fill_color, fill_opacity = get_marker_style_inactive(g)
        radius = max(5, math.log(members) * 2)
        popup = folium.Popup(build_popup_html(g), max_width=300)
        tooltip = f"{g['name']} ({members} members)"
    else:
        fill_color = '#ee9041'
        fill_opacity = 0.7
        radius = 8
        popup = f"<a href='{g['url']}' target='_blank'>{g['name']}</a>"
        tooltip = g['name']

    return folium.CircleMarker(
        location=[g['lat'], g['lon']],
        radius=radius,
        popup=popup,
        tooltip=tooltip,
        color=fill_color,
        fill=True,
        fill_color=fill_color,
        fill_opacity=fill_opacity,
        weight=0
    )

def add_hash_navigation(world_map):
    hash_script = """
    <script>
    (function() {
        function parseHash() {
            var hash = window.location.hash;
            if (hash) {
                var parts = hash.replace('#', '').split('/');
                if (parts.length === 3) {
                    var zoom = parseInt(parts[0]);
                    var lat = parseFloat(parts[1]);
                    var lng = parseFloat(parts[2]);
                    if (!isNaN(zoom) && !isNaN(lat) && !isNaN(lng)) {
                        return {zoom: zoom, lat: lat, lng: lng};
                    }
                }
            }
            return null;
        }
        
        var checkMap = setInterval(function() {
            for (var key in window) {
                if (window[key] instanceof L.Map) {
                    var map = window[key];
                    clearInterval(checkMap);
                    var view = parseHash();
                    if (view) {
                        map.setView([view.lat, view.lng], view.zoom);
                    }
                    
                    map.on('moveend', function() {
                        var center = map.getCenter();
                        var zoom = map.getZoom();
                        history.replaceState(null, null, '#' + zoom + '/' + center.lat.toFixed(4) + '/' + center.lng.toFixed(4));
                    });
                    break;
                }
            }
        }, 100);
    })();
    </script>
    """
    world_map.get_root().html.add_child(folium.Element(hash_script))

def make_base_map(location=[30, 0], zoom_start=2):
    world_map = folium.Map(location=location, zoom_start=zoom_start, tiles=None)
    folium.TileLayer(
        tiles=ESRI_TILE_URL,
        attr=ESRI_ATTR,
        name='Esri World Street Map',
    ).add_to(world_map)
    return world_map

# Create simple world map with orange circle markers (only cluster overlapping)
def create_world_map(groups_enriched, output_file='pydata_world_map.html'):
    world_map = make_base_map()

    coord_groups = defaultdict(list)
    for g in groups_enriched:
        if 'lat' not in g or 'lon' not in g:
            continue
        key = coord_key(g['lat'], g['lon'])
        coord_groups[key].append(g)

    for key, groups in coord_groups.items():
        if len(groups) == 1:
            create_marker(groups[0], style='orange').add_to(world_map)
        else:
            cluster = MarkerCluster(
                options={
                    'spiderfyOnMaxZoom': True,
                    'disableClusteringAtZoom': 12
                }
            ).add_to(world_map)
            for g in groups:
                create_marker(g, style='orange').add_to(cluster)

    add_hash_navigation(world_map)
    world_map.save(output_file)
    print(f"Saved {output_file}")

# Create world map with activity-based styling (only cluster overlapping)
def create_world_map_layers(groups_enriched, output_file='pydata_world_map_active.html'):
    world_map = make_base_map()

    coord_groups = defaultdict(list)
    for g in groups_enriched:
        if 'lat' not in g or 'lon' not in g:
            continue
        key = coord_key(g['lat'], g['lon'])
        coord_groups[key].append(g)

    for key, groups in coord_groups.items():
        if len(groups) == 1:
            create_marker(groups[0], style='layers').add_to(world_map)
        else:
            cluster = MarkerCluster(
                options={
                    'spiderfyOnMaxZoom': True,
                    'disableClusteringAtZoom': 12
                }
            ).add_to(world_map)
            for g in groups:
                create_marker(g, style='layers').add_to(cluster)

    add_hash_navigation(world_map)
    world_map.save(output_file)
    print(f"Saved {output_file}")

# Create world map highlighting inactive groups (only cluster overlapping)
def create_world_map_inactive(groups_enriched, output_file='pydata_world_map_inactive.html'):
    world_map = make_base_map()

    coord_groups = defaultdict(list)
    for g in groups_enriched:
        if 'lat' not in g or 'lon' not in g:
            continue
        key = coord_key(g['lat'], g['lon'])
        coord_groups[key].append(g)

    for key, groups in coord_groups.items():
        if len(groups) == 1:
            create_marker(groups[0], style='inactive').add_to(world_map)
        else:
            cluster = MarkerCluster(
                options={
                    'spiderfyOnMaxZoom': True,
                    'disableClusteringAtZoom': 12
                }
            ).add_to(world_map)
            for g in groups:
                create_marker(g, style='inactive').add_to(cluster)

    add_hash_navigation(world_map)
    world_map.save(output_file)
    print(f"Saved {output_file}")

# Load cached enrichment data from CSV
def load_enrichment_cache(csv_file='pydata_groups.csv'):
    cache = {}
    if Path(csv_file).exists():
        df = pd.read_csv(csv_file)
        for _, row in df.iterrows():
            cache[row['url']] = row.to_dict()
    return cache

async def main():
    print("=" * 60)
    print("Fetching PyData groups from cache...")
    groups = get_cached_pydata_groups()
    print("=" * 60)

    print("Looking for new PyData groups on Meetup...")
    new_groups = await get_pydata_groups()

    if new_groups:
        print(f"Found {len(new_groups)} new groups\n", flush=True)

        print("=" * 60, flush=True)
        print("Geocoding new groups...")
        groups_with_coords = geocode_groups(new_groups)
        for g in groups_with_coords:
            g['country'] = get_country_from_cache(g.get('query', ''))

        print("=" * 60, flush=True)
        print("Append new groups to cache...")
        if groups is not None:
            existing_urls = set(g['url'] for g in groups)
            combined_groups = groups + [g for g in groups_with_coords if g['url'] not in existing_urls]
        else:
            combined_groups = groups_with_coords
        df = pd.DataFrame(combined_groups)
        df.to_csv('pydata_groups.csv', index=False)

        print("Reloading cache...")
        groups = get_cached_pydata_groups()

    print("\n" + "=" * 60)
    if len(groups) < 135:
        raise Exception(f"Expected at least 135 groups in cache, found {len(groups)}. Scrape may have been incomplete.")

    print("\n" + "=" * 60)
    print(f"Enriching {len(groups_with_coords)} groups with event details...")
    print("=" * 60, flush=True)

    enrichment_cache = load_enrichment_cache()
    print(f"Loaded {len(enrichment_cache)} groups from enrichment cache\n", flush=True)

    all_groups_enriched = []
    fresh_count = 0
    cached_count = 0
    failed_count = 0

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 800})

        for i, group in enumerate(groups):
            print(f"[{i + 1}/{len(groups)}] {group['name']}...", end=' ', flush=True)

            try:
                details = await get_group_details_public(page, group['url'] + '/')
                enriched = {**group, **details}
                all_groups_enriched.append(enriched)

                days = details.get('days_since_last_event')
                days_str = f"{days} days ago" if days is not None else "never"
                upcoming = "✓" if details.get('has_upcoming_events') else "✗"
                print(f"✓ {details.get('past_events_count', 0) or 0} events, last: {days_str}, upcoming: {upcoming}", flush=True)
                fresh_count += 1
            except Exception as e:
                cached = enrichment_cache.get(group['url'])
                if cached and 'past_events_count' in cached:
                    enriched = {**group}
                    for key in ['past_events_count', 'organizer_count', 'primary_organizer',
                                'last_event_date', 'has_upcoming_events', 'days_since_last_event',
                                'events_url', 'leaders_url']:
                        if key in cached and pd.notna(cached.get(key)):
                            enriched[key] = cached[key]
                    all_groups_enriched.append(enriched)

                    days = enriched.get('days_since_last_event')
                    days_str = f"{days} days ago" if days is not None and pd.notna(days) else "never"
                    upcoming = "✓" if enriched.get('has_upcoming_events') else "✗"
                    print(f"⟳ {enriched.get('past_events_count', 0) or 0} events, last: {days_str}, upcoming: {upcoming} [cached]", flush=True)
                    cached_count += 1
                else:
                    print(f"✗ {type(e).__name__} (no cache)", flush=True)
                    all_groups_enriched.append(group)
                    failed_count += 1

        await browser.close()

    print("\n" + "=" * 60)
    print(f"Enrichment complete: {fresh_count} fresh, {cached_count} cached, {failed_count} failed")
    print("Generating maps...")
    print("=" * 60, flush=True)

    create_world_map(all_groups_enriched, 'pydata_world_map.html')
    create_world_map_layers(all_groups_enriched, 'pydata_world_map_active.html')
    create_world_map_inactive(all_groups_enriched, 'pydata_world_map_inactive.html')

    df = pd.DataFrame(all_groups_enriched)
    df.to_csv('pydata_groups.csv', index=False)
    print("Saved pydata_groups.csv", flush=True)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60, flush=True)

if __name__ == "__main__":
    asyncio.run(main())