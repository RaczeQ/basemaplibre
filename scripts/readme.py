"""Draw the images of the README to images/."""

from pathlib import Path
from typing import Literal

import contextily as cx
import geopandas
import matplotlib
import matplotlib.pyplot as plt
from gallery import HEIGHT, WIDTH, draw
from matplotlib.figure import Figure

import basemaplibre as bml

IMAGES = Path(__file__).parent.parent / "images"
NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
STYLES = [
    "OpenFreeMap.Liberty",
    "VersaTiles.Toner",
    "CartoDB.DarkMatter",
    "Maptoolkit.Hiking",
    "swisstopo.BaseMap",
    "OpenHistoricalMap.JapaneseScroll",
    "BasemapDE.Color",
    "Mapterhorn.Relief",
    "USGS.Imagery",
]


def save(figure: Figure, name: str) -> None:
    """Save `figure` to images/."""
    figure.savefig(IMAGES / f"{name}.webp", dpi=200, pil_kwargs={"quality": 85})
    plt.close(figure)


def compare() -> None:
    """Draw a basemap in EPSG:3035 by contextily and basemaplibre."""
    places = geopandas.read_file(f"{NATURAL_EARTH}ne_50m_populated_places_simple.geojson")
    capitals = places[places.featurecla == "Admin-0 capital"].cx[-12:32, 43:61]
    figure, axs = plt.subplots(1, 2, figsize=(9, 3.6), layout="constrained")
    for ax, (name, module) in zip(axs, [("contextily", cx), ("basemaplibre", bml)], strict=True):
        capitals.to_crs(3035).plot(ax=ax, color="crimson", markersize=capitals.pop_max / 5e4)
        ax.set_axis_off()
        ax.set_title(f"{name}.add_basemap(ax, crs=3035)")
        module.add_basemap(ax, crs=3035, attribution_size=6)
    save(figure, "compare")


def labels() -> None:
    """Draw a choropleth between a basemap and its labels."""
    countries = geopandas.read_file(f"{NATURAL_EARTH}ne_110m_admin_0_countries.geojson")
    europe = countries[countries.CONTINENT == "Europe"].to_crs(3035)
    europe["gdp"] = europe.GDP_MD / europe.POP_EST * 1e6
    figure, axs = plt.subplots(1, 2, figsize=(9, 4.4), layout="constrained")
    choices: list[Literal[True, "above"]] = [True, "above"]
    for ax, choice in zip(axs, choices, strict=True):
        europe.plot("gdp", ax=ax, cmap="YlGn", alpha=0.8, edgecolor="white")
        ax.axis((2.5e6, 6.5e6, 1.4e6, 5.2e6))
        ax.set_axis_off()
        ax.set_title(f"labels={choice!r}")
        bml.add_basemap(ax, crs=3035, source="CartoDB.Voyager", labels=choice, attribution_size=6)
    save(figure, "labels")


def styles() -> None:
    """Draw some of `STYLES`."""
    height = 3 * (3 * HEIGHT / WIDTH + 0.22)
    figure, axs = plt.subplots(3, 3, figsize=(9, height), layout="constrained")
    for ax, name in zip(axs.flat, STYLES, strict=True):
        ax.set_title(name, fontsize=9, pad=3)
        draw(ax, name, attribution_size=4)
    save(figure, "styles")


if __name__ == "__main__":
    matplotlib.use("agg")
    IMAGES.mkdir(exist_ok=True)
    compare()
    labels()
    styles()
