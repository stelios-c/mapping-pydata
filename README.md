# Mapping PyData

I created this project out of a desire for a better map of the international PyData community than the [one available on Meetup](https://www.meetup.com/pro/pydata/).

This repo consists of three main parts:

- [PyDataMap.py](./PyDataMap.py) a script which scrapes Meetup.com for group and event data, populates the [geocode_cache.json](./geocode_cache.json) with each group and it's location based on the group name itself (due to issues with the city field in Meetup), updates [pydata_groups.csv](./pydata_groups.csv) which stores data about upcoming and past events in aggregate by group name, and then produces static versions of the maps. This script is scheduled to run daily.

- [MapsExplained.py](./) a [marimo](https://marimo.io/) notebook which can be used to create and explore the maps based on cached data in [geocode_cache.json](./geocode_cache.json) and [pydata_groups.csv](./pydata_groups.csv). This is intended to make it easy to create your own maps with this data. It also includes some example queries that can be made against the collected data i.e. top 10 most recent events.

- The maps (which are hosted via GitHub Pages): 
    - [World Map](https://hevansdev.github.io/mapping-pydata/pydata_world_map.html) a 1:1 recreation of the [map from Meetup](https://www.meetup.com/pro/pydata/) but with the location of Meetups corrected.
    - [World Map Active](https://hevansdev.github.io/mapping-pydata/pydata_world_map_active.html) a map intended to make it easy to spot active PyData groups with a view towards attending / speaking at them.
    - [World Map Inactive](https://hevansdev.github.io/mapping-pydata/pydata_world_map_inactive.html) a map intended to draw attention to groups that haven't hosted an event in a while. You should consider volunteering for, speaking at, or sponsoring these groups to help them out.

## FAQ

### Why is my group shown in the wrong location?

I am using [geopy](https://github.com/geopy/geopy) to geoencode group names to produce coordinates for each group. This is not a perfect process particularly as many groups deviate from the `PyData {location}` naming convention. To get around this I've added a series of aliases (or hints) to the geocode cache as shown below.

```json
"hints": {
    "PyMC Online Meetup": null,
    "PyData En Espa\u00f1ol Global.": null,
    "NEO AI - a PyData Group": "Cleveland, Ohio, USA",
    "PyData Ireland": "Dublin, Ireland",
    "PyData T&T": "Port of Spain, Trinidad and Tobago",
    "PyData Katsina": "Katsina, Nigeria",
    "Copenhagen Julia Meetup Group": "Copenhagen, Denmark",
    "PyData Boston - Cambridge": "Boston, Massachusetts, USA",
    "PyData Athens": "Athens, Greece",
    "Pydata Belgium": "Brussels, Belgium",
    ...
```

If your group is shown in the wrong location you can raise an issue or a PR with an alias for your group (or manually edit the latitude and longitude in the coords section of the cache file).

## Contributing

If you have an idea for how to improe this project please fork and raise PRs. [Contact Hugh](mailto:hughevans.dev) for all other inquiries. 