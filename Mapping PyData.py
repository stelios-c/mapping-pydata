import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _():
    import re
    import marimo as mo
    import requests
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright
    return async_playwright, mo


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
    import folium
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter

    geolocator = Nominatim(user_agent="pydata_mapper")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    # Manual overrides for edge cases
    LOCATION_OVERRIDES = {
        'NEO AI - a PyData Group': 'Cleveland, Ohio, USA',
        'PyData Ireland': 'Dublin, Ireland',
        'PyData T&T': 'Port of Spain, Trinidad and Tobago',
        'PyData En Español Global.': None,  # Skip - no fixed location
        'PyData Katsina': 'Katsina, Nigeria',
        'Copenhagen Julia Meetup Group': 'Copenhagen, Denmark',
        'PyData Boston - Cambridge': 'Boston, Massachusetts, USA',
        'PyData Athens': 'Athens, Greece',
        'Pydata Belgium': 'Brussels, Belgium',
        'Datenanalyse, Data Science und Statistik - PyData Dortmund': 'Dortmund, Germany',
        'PyData Bucharest': 'Bucharest, Romania',
        'PyData Dubai meetup': 'Dubai, UAE',
        'PyMC Online Meetup': None,  # Skip - online only
        'Charlottesville Data Science (a PyData Group)': 'Charlottesville, Virginia, USA',
        'PyData Miami / Machine Learning Meetup': 'Miami, Florida, USA',
        'Dallas Data Engineers - a PyData Group': 'Dallas, Texas, USA',
        'Data Engineering Pilipinas - a PyData group': 'Manila, Philippines',
    }

    def extract_city_from_name(name):
        # Check overrides first
        if name in LOCATION_OVERRIDES:
            return LOCATION_OVERRIDES[name]
    
        # Clean up the name to get city
        city = name.replace('PyData ', '').replace(' Meetup', '').replace(' Group', '')
        city = city.replace(' - a PyData Group', '').replace(', UK', '')
    
        # Some names need country hints for accurate geocoding
        country_hints = {
            'Birmingham': 'Birmingham, UK',
            'Cambridge': 'Cambridge, UK', 
            'Manchester': 'Manchester, UK',
            'Bristol': 'Bristol, UK',
            'Cardiff': 'Cardiff, UK',
            'Leeds': 'Leeds, UK',
            'London': 'London, UK',
            'OMR': 'Chennai, India',  # PyData OMR is in Chennai
            'Südwest': 'Heidelberg, Germany',
            'Rhein-Main': 'Frankfurt, Germany',
            'Trojmiasto': 'Gdansk, Poland',
            'GRX': 'Granada, Spain',
            'RJ': 'Rio de Janeiro, Brazil',
            'T&T': 'Port of Spain, Trinidad',
            'DC Virtual': 'Washington DC, USA',
            'SLO': 'San Luis Obispo, California, USA',
            'PDX': 'Portland, Oregon, USA',
            'NYC': 'New York City, USA',
            'Boston - Cambridge': 'Boston, Massachusetts, USA',
        }
    
        for key, value in country_hints.items():
            if key in city:
                return value
    
        return city

    # Geocode each group
    _groups_with_coords = []
    for _g in groups:
        city = extract_city_from_name(_g['name'])
    
        if city is None:  # Skip groups with no location
            print(f"⊘ {_g['name']} (skipped)")
            continue
        
        try:
            location = geocode(city)
            if location:
                _groups_with_coords.append({
                    **_g,
                    'city': city,
                    'lat': location.latitude,
                    'lon': location.longitude
                })
                print(f"✓ {_g['name']} -> {city} ({location.latitude:.2f}, {location.longitude:.2f})")
            else:
                print(f"✗ {_g['name']} -> {city} (not found)")
        except Exception as e:
            print(f"✗ {_g['name']} -> {city} (error: {e})")

    print(f"\nGeocoded {len(_groups_with_coords)} of {len(groups)} groups")
    groups_with_coords = _groups_with_coords
    return folium, groups_with_coords


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
