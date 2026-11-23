"""Write the style gallery, a page with a map of every style of `STYLES`, to docs/gallery.md."""

from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import matplotlib
import matplotlib.pyplot as plt
import pyproj
from matplotlib.axes import Axes

import basemaplibre as bml

DOCS = Path(__file__).parent.parent / "docs"
IMAGES = DOCS / "gallery"
WIDTH, HEIGHT = 4, 8 / 3  # inches

Place = tuple[float, float, float]  # longitude, latitude, half of the width in Web Mercator meters
TOKYO, FUJI = (139.767, 35.681, 2000), (138.73, 35.38, 20000)


class Service(NamedTuple):
    """What the gallery says of a service, and where it draws its styles."""

    coverage: str
    terms: str
    place: Place
    attribution: str | None = None  # of styles that carry none


SERVICES = {
    "OpenFreeMap": Service("World", "[OpenFreeMap](https://openfreemap.org/tos/)", TOKYO),
    "VersaTiles": Service(
        "World",
        "[VersaTiles](https://github.com/versatiles-org/versatiles-documentation/blob/main/guides/use_tiles_versatiles_org.md)",
        TOKYO,
    ),
    "CartoDB": Service(
        "World", "[CARTO](https://carto.com/legal/basemap-terms/) (asks for an API key)", TOKYO
    ),
    "Maptoolkit": Service("World", "[Maptoolkit](https://docs.maptoolkit.org/map-styles/)", TOKYO),
    "OpenHistoricalMap": Service(
        "World, drawn as of today",
        "[OpenHistoricalMap](https://wiki.openstreetmap.org/wiki/OpenHistoricalMap/Reuse) (CC0)",
        (-0.12, 51.51, 15000),
    ),
    "MapLibre": Service("World, low zooms", "MapLibre's demo", (10, 30, 8_000_000)),
    "BasemapDE": Service(
        "Germany",
        "[basemap.de](https://sgx.geodatenzentrum.de/public/gdz/lizenz/deu/nutzungsbedingungen_basemapde.pdf)",
        (13.405, 52.52, 2000),
    ),
    "swisstopo": Service(
        "Switzerland",
        "[swisstopo](https://www.geo.admin.ch/en/general-terms-of-use-fsdi)",
        (8.542, 47.377, 2000),
    ),
    "IGN": Service(
        "France",
        "[Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/limites-d-usage/)"
        " (Etalab 2.0). The maps carry no attribution, so pass `attribution=` yourself",
        (2.352, 48.857, 2000),
        "© IGN",
    ),
    "PDOK": Service(
        "Netherlands",
        "[PDOK](https://www.pdok.nl/) (CC BY 4.0)."
        " The maps carry no attribution, so pass `attribution=` yourself",
        (4.893, 52.373, 800),
        "© Kadaster / PDOK (CC BY 4.0)",
    ),
    "GSI": Service(
        "Japan", "[GSI](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)", TOKYO
    ),
    "Mapterhorn": Service(
        "World, terrain. `Mapterhorn.Hillshade` is transparent, to shade another basemap",
        "[Mapterhorn](https://mapterhorn.com/attribution)",
        FUJI,
    ),
    "EOX": Service(
        "World, imagery of 2024 and 2016",
        "[EOX](https://cloudless.eox.at/) (2024: CC BY-NC-SA 4.0, non-commercial; 2016: CC BY 4.0)",
        (31.72, 30.02, 10000),
    ),
    "USGS": Service("United States, imagery", "USGS (public domain)", (-112.11, 36.08, 6000)),
}
# Where styles are drawn that do not suit the place of their service.
PLACES: dict[str, Place] = {
    "VersaTiles.Satellite": (55.139, 25.112, 5000),
    "Maptoolkit.Cycling": FUJI,
    "Maptoolkit.Hiking": FUJI,
    "Maptoolkit.Winter": FUJI,
    "OpenHistoricalMap.JapaneseScroll": (137.5, 36.5, 900_000),
    "OpenHistoricalMap.Woodblock": (14, 49, 1_300_000),
    "BasemapDE.Topo": (10.615, 51.8, 15000),
    "swisstopo.BaseMapWinter": (7.749, 46.021, 4000),
    "swisstopo.ImageryBaseMap": (7.659, 45.976, 5000),
    "IGN.Ortho": (-1.511, 48.636, 500),
    "PDOK.Luchtfoto": (7.1914, 53.0067, 700),
    "GSI.Photo": (134.694, 34.839, 500),
}


def draw(ax: Axes, name: str, attribution_size: float = 5) -> None:
    """Draw a style at its place, at the size and aspect of `ax`."""
    service = SERVICES[name.split(".")[0]]
    place = PLACES.get(name, FUJI if "Terrain" in name else service.place)
    longitude, latitude, half_width = place
    x, y = pyproj.Transformer.from_crs(4326, 3857, always_xy=True).transform(longitude, latitude)
    half_height = half_width * HEIGHT / WIDTH
    ax.axis((x - half_width, x + half_width, y - half_height, y + half_height))
    ax.set_aspect("equal")
    ax.set_axis_off()
    # The attribution of styles that carry one is None: theirs.
    attribution = None if name.startswith(("IGN.Ortho", "PDOK.Luchtfoto")) else service.attribution
    bml.add_basemap(ax, source=name, attribution=attribution, attribution_size=attribution_size)


def main() -> None:
    """Draw the styles and write the page."""
    matplotlib.use("agg")
    IMAGES.mkdir(exist_ok=True)
    services = defaultdict(list)
    for name in bml.STYLES:
        services[name.split(".")[0]].append(name)
    page = [
        "# Style gallery",
        (
            "The names of `STYLES`, for `add_basemap(ax, source=...)`. They load without an API"
            " key, but check the terms of each service before heavy use."
        ),
        (
            "Places are labelled in the local language and in Latin script by OpenFreeMap and"
            " Maptoolkit, in Latin script only by CARTO, and in the local language only by"
            " VersaTiles."
        ),
    ]
    for prefix, names in services.items():
        service = SERVICES[prefix]
        page += [
            f"## {prefix}",
            f"Coverage: {service.coverage}. Terms: {service.terms}.",
            '<div class="grid cards" markdown>',
        ]
        for name in names:
            print(name, flush=True)
            figure = plt.figure(figsize=(WIDTH, HEIGHT))
            draw(figure.add_axes((0, 0, 1, 1)), name)
            figure.savefig(IMAGES / f"{name}.webp", dpi=200, pil_kwargs={"quality": 85})
            plt.close(figure)
            page.append(f"-   ![{name}](gallery/{name}.webp)\n\n    `{name}`")
        page.append("</div>")
    (DOCS / "gallery.md").write_text("\n\n".join(page) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
