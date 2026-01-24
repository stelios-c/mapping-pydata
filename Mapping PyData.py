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
    return async_playwright, folium, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Meetup is horrendus, I don't like their API. I want to go round to Meetup's house and bend all their spoons.

    Here's a janky script to extract a complete list of PyData groups from https://www.meetup.com/pro/pydata/
    """)
    return


@app.cell
async def _(async_playwright):
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
                                allGroups.set(url, {
                                    name: el.querySelector('h3')?.textContent || '',
                                    url: url
                                });
                            }
                        });
                    
                        console.log("Collected: " + allGroups.size);
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
    return (groups,)


@app.cell
def _(groups):
    print(groups)
    return


@app.cell
def _(groups):
    import json
    from pathlib import Path
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter

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
    return (groups_with_coords,)


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
    _uk_groups = [_g for _g in groups_with_coords if is_in_uk(_g['lat'], _g['lon'])]
    print(f"Found {len(_uk_groups)} UK groups:")
    for _g in _uk_groups:
        print(f"  {_g['name']}")

    # Create UK-centered map
    _m = folium.Map(location=[54.5, -2], zoom_start=6)

    for _g in _uk_groups:
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
    return


if __name__ == "__main__":
    app.run()
