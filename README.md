# basemaplibre

Basemaps for [matplotlib](https://matplotlib.org/) and [GeoPandas](https://geopandas.org/) from [MapLibre styles](https://maplibre.org/maplibre-style-spec/), with the parameters of [contextily](https://contextily.readthedocs.io/)'s `add_basemap`.

contextily downloads raster tiles in Web Mercator, merges them and warps them to the CRS of your data. `basemaplibre` renders the style (vector tiles, labels, icons) with [ml2drender](https://github.com/Kanahiro/ml2drender) for the extent of the axes, at their resolution and directly in their CRS, so labels stay upright and sharp. No GPU, no browser, no system libraries.

<p align="center">
    <img alt="GitHub" src="https://img.shields.io/github/license/raczeq/basemaplibre?logo=mit&logoColor=%23fff">
    <img src="https://img.shields.io/github/checks-status/raczeq/basemaplibre/main?logo=GitHubActions&logoColor=%23fff" alt="Checks">
    <a href="https://github.com/raczeq/basemaplibre/actions/workflows/ci-prod.yml" target="_blank"><img alt="GitHub Workflow Status - PROD" src="https://img.shields.io/github/actions/workflow/status/raczeq/basemaplibre/ci-prod.yml?label=build-prod&logo=GitHubActions&logoColor=%23fff"></a>
    <a href="https://results.pre-commit.ci/latest/github/raczeq/basemaplibre/main" target="_blank"><img src="https://results.pre-commit.ci/badge/github/raczeq/basemaplibre/main.svg" alt="pre-commit.ci status"></a>
    <a href="https://app.codecov.io/gh/raczeq/basemaplibre/tree/main"><img alt="Codecov" src="https://img.shields.io/codecov/c/github/raczeq/basemaplibre?logo=codecov&logoColor=%23fff"></a>
    <a href="https://pypi.org/project/basemaplibre" target="_blank"><img src="https://img.shields.io/pypi/v/basemaplibre?color=%2334D058&label=pypi%20package&logo=pypi&logoColor=%23fff" alt="Package version"></a>
    <a href="https://pypi.org/project/basemaplibre" target="_blank"><img src="https://img.shields.io/pypi/pyversions/basemaplibre.svg?color=%2334D058&logo=python&logoColor=%23fff" alt="Supported Python versions"></a>
</p>

[Documentation](https://raczeq.github.io/basemaplibre/) · [Style gallery](https://raczeq.github.io/basemaplibre/gallery/) · [API reference](https://raczeq.github.io/basemaplibre/api/)

## Installation

```bash
pip install basemaplibre
```

## Usage

```python
import geopandas
import basemaplibre as bml

gdf = geopandas.read_file("districts.gpkg")
ax = gdf.plot(alpha=0.5, edgecolor="k")
bml.add_basemap(ax, crs=gdf.crs, source="OpenFreeMap.Positron")
```

| | |
|---|---|
| `add_basemap(ax, ...)` | Draws a style under the data of `ax`. |
| `add_attribution(ax, text, ...)` | Writes `text` in the bottom right corner of `ax`, wrapped to its width, on a translucent white box as MapLibre does. |
| `set_cache_dir(path)` | Keeps downloads in `path`, reused by later sessions that set it again, instead of a temporary directory removed at exit. |
| `STYLES` | Named styles that load without an API key, for `source`. |

## Differences from contextily

- `source` is a MapLibre style: a `dict`, the URL of its JSON, a name of `STYLES` (default `OpenFreeMap.Liberty`) or a local `.json` file. Other sources (an `xyzservices` provider, a URL of raster tiles, a raster file) are left to `contextily.add_basemap`, with a `UserWarning`. contextily is not a dependency: install it for those.
- The style is drawn directly in `crs` (anything `pyproj.CRS.from_user_input` reads) if ml2drender [supports the projection](https://github.com/Kanahiro/ml2drender#projected-coordinate-reference-systems), so `resampling` is ignored. Axes that stretch latitudes, as GeoPandas does in EPSG:4326, get the projection they show, so labels keep their shape.
- `zoom` is contextily's zoom of 256-pixel tiles (the style is evaluated at MapLibre zoom `zoom - 1`); `"auto"` draws the style at its size on a web page.
- The basemap is rendered when it is added, and again when the axes are drawn with other limits, at another size or at another dpi: it stays sharp and up to date after zooming, panning, `fig.tight_layout()` or `fig.savefig(dpi=300)`. Rendering may download tiles, and its errors are raised where the figure is drawn. The image has the dpi the figure is drawn at, but 200 pixels to the inch at least.
- New: `labels=False` drops the labels and icons, `labels="only"` draws only them, above the data, and `labels="above"` draws the map under the data and its labels above it; `pixel_ratio` fixes the resolution; `load` replaces fetching with HTTPX. OpenHistoricalMap's styles are drawn as of today, as on its website.
- Downloads are cached on disk as in contextily (`set_cache_dir` keeps them across sessions), but for the style and its TileJSON, which name the current tiles. Failed requests are tried twice more.

## Styles

`STYLES` has maps of the world (OpenFreeMap, VersaTiles, CARTO, Maptoolkit, OpenHistoricalMap, MapLibre) and of national mapping agencies (basemap.de, swisstopo, IGN, PDOK, GSI), terrain (Mapterhorn) and imagery (VersaTiles, EOX, USGS, GSI, PDOK, IGN). The [gallery](https://raczeq.github.io/basemaplibre/gallery/) shows each of them, with the coverage and terms of their services: check the terms before heavy use.

`Mapterhorn.Hillshade` is transparent, to shade another basemap (here, under its labels):

```python
bml.add_basemap(ax, source="OpenFreeMap.Positron", labels="above")
bml.add_basemap(ax, source="Mapterhorn.Hillshade")
```

## Development

```bash
uv sync                # install
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run tox             # tests
uv run tox -e docs     # execute the notebooks, draw the gallery, build the docs to site/
uv run zensical serve  # preview them
```

The notebooks in `examples/` are kept without outputs: they are executed when the docs are built, on release.
