"""
Tests of basemaplibre.

Nothing is fetched from the internet: styles are inline or served locally, and contextily is a stub.
"""

import asyncio
import concurrent.futures
import datetime
import io
import json
import math
import pickle
import sys
import tempfile
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from unittest import mock

import httpx
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

import basemaplibre as bml
from basemaplibre import _render, _source

matplotlib.use("agg")

RADIUS = 6378137.0
TURN = 2 * math.pi * RADIUS
RED, GREEN, BLUE, BLACK = [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [0, 0, 0, 255]
WHITE = [255, 255, 255, 255]


def mercator(lng, lat):
    return RADIUS * math.radians(lng), RADIUS * math.log(
        math.tan(math.pi / 4 + math.radians(lat) / 2)
    )


# A square of Web Mercator around 15 E 45 N that 384 CSS pixels show at MapLibre zoom 4.
CENTER = mercator(15, 45)
HALF = TURN * 384 / 512 / 2**4 / 2
EXTENT = (CENTER[0] - HALF, CENTER[0] + HALF, CENTER[1] - HALF, CENTER[1] + HALF)
SQUARE = [[[13, 43.5], [17, 43.5], [17, 46.5], [13, 46.5], [13, 43.5]]]
CORNER = (EXTENT[0] + 1, EXTENT[3] - 1)


def style(background="#ffffff", **source):
    """A background and a red square at 15 E 45 N; `source` is added to its GeoJSON source."""
    data = {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": SQUARE},
    }
    return {
        "version": 8,
        "sources": {"square": {"type": "geojson", "data": data, **source}},
        "layers": [
            {"id": "bg", "type": "background", "paint": {"background-color": background}},
            {
                "id": "square",
                "type": "fill",
                "source": "square",
                "paint": {"fill-color": "#ff0000"},
            },
        ],
    }


STYLE = style()
# Black below MapLibre zoom 3.5, then red, green (from 4.5) and blue (from 5.5).
ZOOMS = ["step", ["zoom"], "#000000", 3.5, "#ff0000", 4.5, "#00ff00", 5.5, "#0000ff"]


def axes(extent=EXTENT):
    """Axes filling a 4 x 4 inch figure at 96 dpi (384 pixels and, automatically, CSS pixels)."""
    figure = plt.figure(figsize=(4, 4), dpi=96)
    ax = figure.add_axes((0, 0, 1, 1))
    ax.axis(extent)
    return ax


def basemap(ax=None, **options):
    """The image ``add_basemap`` draws on ``ax`` (new axes by default)."""
    ax = axes() if ax is None else ax
    bml.add_basemap(ax, **options)
    return ax.images[-1]


def pixel(artist, x, y):
    """The pixel of the image of ``artist`` at ``x``, ``y``."""
    image = np.asarray(artist.get_array())
    left, right, bottom, top = artist.get_extent()
    height, width = image.shape[:2]
    return image[
        int((top - y) / (top - bottom) * height), int((x - left) / (right - left) * width)
    ].tolist()


class SourceTest(unittest.TestCase):
    def test_resolve(self):
        resolve = _source.resolve
        self.assertEqual(resolve(None), bml.STYLES["OpenFreeMap.Liberty"])
        self.assertEqual(resolve("CartoDB.Positron"), bml.STYLES["CartoDB.Positron"])
        self.assertEqual(
            resolve("CartoDB.PositronNoLabels"), bml.STYLES["CartoDB.PositronNoLabels"]
        )
        self.assertEqual(resolve("Mapterhorn.Hillshade")["layers"][0]["type"], "hillshade")
        self.assertTrue(
            resolve("VersaTiles.NaturalDarkTerrain").endswith("/natural-dark-terrain/style.json")
        )
        self.assertEqual(resolve("Maptoolkit.Hiking"), "https://styles.maptoolkit.org/hiking.json")
        self.assertEqual(
            resolve("https://example.com/style.json"), "https://example.com/style.json"
        )
        self.assertEqual(resolve("s3://bucket/style.json"), "s3://bucket/style.json")
        self.assertIs(resolve(STYLE), STYLE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "style.json")
            path.write_text(json.dumps(STYLE))
            self.assertEqual(resolve(path), STYLE)
            self.assertEqual(resolve(str(path)), STYLE)
        # Not styles: contextily's sources.
        tiles = "https://tile.example/{z}/{x}/{y}.png"
        for source in [
            "OpenStreetMap.Mapnik",
            "CartoDB.PositronOnlyLabels",
            "cartodb positron",
            tiles,
            {"url": tiles},
            Path("map.tif"),
            42,
        ]:
            with self.subTest(source=source):
                self.assertIsNone(resolve(source))

    def test_misspelled(self):
        with mock.patch.dict(sys.modules, {"xyzservices": None}):
            self.assertEqual(_source.misspelled("openfreemap.liberty"), "OpenFreeMap.Liberty")
            self.assertEqual(_source.misspelled("CartoDB.Voyager2"), "CartoDB.Voyager")
            self.assertEqual(
                _source.misspelled("CartoDB.PositronOnlyLabels"), "CartoDB.PositronNoLabels"
            )
            for source in [
                "OpenStreetMap.Mapnik",
                "https://tile.example/{z}/{x}/{y}.png",
                Path("map.tif"),
                42,
            ]:
                with self.subTest(source=source):
                    self.assertIsNone(_source.misspelled(source))
        # A provider of xyzservices is contextily's, however close.
        xyzservices = types.SimpleNamespace(
            providers=types.SimpleNamespace(query_name=lambda name: name)
        )
        with mock.patch.dict(sys.modules, {"xyzservices": xyzservices}):
            self.assertIsNone(_source.misspelled("CartoDB.PositronOnlyLabels"))

    def test_labels(self):
        layers = [
            {"id": "bg", "type": "background"},
            {"id": "names", "type": "symbol"},
            {"id": "roads", "type": "line"},
        ]
        spec = {"version": 8, "sources": {}, "layers": layers}
        self.assertIs(_source.with_labels(spec, True), spec)
        self.assertEqual(
            [layer["id"] for layer in _source.with_labels(spec, False)["layers"]], ["bg", "roads"]
        )
        self.assertEqual(
            [layer["id"] for layer in _source.with_labels(spec, "only")["layers"]], ["names"]
        )
        self.assertEqual(len(spec["layers"]), 3)  # the style passed in is left as it was
        with self.assertRaises(ValueError):
            _source.with_labels(spec, "none")

    def test_preprocess_style(self):
        # Styles of OpenHistoricalMap's tiles: the layers of features get the condition, with their
        # own filter if any, in its syntax.
        layers = [
            {"id": "bg", "type": "background"},
            {
                "id": "land",
                "type": "fill",
                "source": "ohm",
                "filter": ["==", ["get", "class"], "land"],
            },
            {
                "id": "water",
                "type": "fill",
                "source": "ohm",
                "filter": ["all", ["==", "class", "water"]],
            },
            {"id": "roads", "type": "line", "source": "ohm"},
            {"id": "names", "type": "symbol", "source": "ohm"},
            {"id": "image", "type": "raster", "source": "r"},
        ]
        tiles = "https://vtiles.openhistoricalmap.org/maps/ohm/{z}/{x}/{y}.pbf"
        spec = {
            "version": 8,
            "sources": {"ohm": {"type": "vector", "tiles": [tiles]}},
            "layers": layers,
        }
        dated = _source.preprocess_style(spec, True)["layers"]
        self.assertEqual(
            ["filter" in layer for layer in dated], [False, True, True, True, True, False]
        )
        expression = dated[3]["filter"]
        self.assertEqual(dated[1]["filter"], ["all", layers[1]["filter"], expression])
        year = expression[1][2][2]  # today, as a decimal year
        self.assertTrue(datetime.date.today().year <= year < datetime.date.today().year + 1)
        legacy = ["all", ["any", ["!has", "start_decdate"], ["<=", "start_decdate", year]]]
        legacy.append(["any", ["!has", "end_decdate"], [">", "end_decdate", year]])
        self.assertEqual(dated[2]["filter"], ["all", layers[2]["filter"], legacy])
        self.assertNotIn("filter", layers[3])  # the style passed in is left as it was
        # With the labels chosen first.
        self.assertEqual(
            [layer["id"] for layer in _source.preprocess_style(spec, "only")["layers"]], ["names"]
        )
        # Other styles are left as they are.
        for url in [
            "https://tiles.openfreemap.org/planet",
            "https://openhistoricalmap.org.example.com/tiles.json",
        ]:
            with self.subTest(url=url):
                other = {"sources": {"s": {"type": "vector", "url": url}}, "layers": layers}
                self.assertIs(_source.preprocess_style(other, True), other)
        self.assertIs(_source.preprocess_style(STYLE, True), STYLE)

    def test_filter_syntax(self):
        cases = {
            "legacy": [
                ["==", "class", "land"],
                ["in", "class", "a", "b"],
                ["!has", "name"],
                ["has", "$id"],
                "x",
            ],
            "expression": [
                ["==", ["get", "class"], "land"],
                ["in", "a", ["get", "class"]],
                ["has", "name", {}],
            ],
            None: [True, ["has", "name"], ["all"], ["any", True, ["has", "name"]]],
        }
        cases["legacy"].append(["all", ["has", "name"], ["==", "class", "land"]])
        cases["expression"].append(
            ["all", ["==", "class", "land"], ["!", ["has", "name"]]]
        )  # read as one
        for syntax, filters in cases.items():
            for layer_filter in filters:
                with self.subTest(layer_filter=layer_filter):
                    self.assertEqual(_source._syntax(layer_filter), syntax)

    def test_attribution_text(self):
        html = '<a href="https://osm.org">&copy; OpenStreetMap</a>  contributors'
        self.assertEqual(
            _render.attribution_text([html, None, 3, "Tiles", html]),
            "© OpenStreetMap contributors | Tiles",
        )
        # Texts joined before (and wrapped, as drawn) are taken apart to find those repeated.
        self.assertEqual(_render.attribution_text(["A | B", "B |\nC"]), "A | B | C")
        # One part of another is left out.
        texts = [html, "Tiles", "© OpenStreetMap contributors · ESA"]
        self.assertEqual(
            _render.attribution_text(texts), "Tiles | © OpenStreetMap contributors · ESA"
        )


class AddBasemapTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_add_basemap(self):
        ax = axes()
        self.assertIsNone(bml.add_basemap(ax, source=style(attribution="<b>&copy; Square</b>")))
        self.assertEqual(ax.axis(), EXTENT)  # the limits are kept
        [artist] = ax.images
        np.testing.assert_allclose(artist.get_extent(), EXTENT)
        # 200 pixels to the inch of the axes (4 x 4 inches).
        self.assertEqual(artist.get_array().shape, (800, 800, 4))
        self.assertEqual(pixel(artist, *CENTER), RED)
        self.assertEqual(pixel(artist, EXTENT[0] + 1, EXTENT[2] + 1), WHITE)
        self.assertEqual([text.get_text() for text in ax.texts], ["© Square"])
        self.assertEqual(artist.get_interpolation(), "bilinear")

    def test_zoom(self):
        spec = style(background=ZOOMS)

        def color(**options):
            return pixel(basemap(source=spec, attribution=False, **options), *CORNER)

        # Automatic: 96 CSS pixels to the inch, so MapLibre zoom 4 in a 4-inch figure whatever its
        # dpi.
        self.assertEqual(color(), RED)
        self.assertEqual(color(zoom_adjust=1), GREEN)
        self.assertEqual(color(zoom=6), GREEN)  # contextily's zoom 6 is MapLibre's 5
        self.assertEqual(color(zoom=6, zoom_adjust=1), BLUE)
        self.assertEqual(color(zoom=4, zoom_adjust=-1), BLACK)
        # Fractional, as in MapLibre: 5.4 and 5.6 are MapLibre's 4.4 and 4.6.
        self.assertEqual(
            (color(zoom=5.4), color(zoom=5.6), color(zoom_adjust=0.6)), (RED, GREEN, GREEN)
        )
        # A figure of 200 dpi or more gets its own resolution (1200 x 1200 pixels here).
        ax = axes()
        ax.figure.set_dpi(300)
        artist = basemap(ax, source=spec)
        self.assertEqual((artist.get_array().shape, pixel(artist, *CORNER)), ((1200, 1200, 4), RED))
        # A zoom too low for the extent: one CSS pixel, still at 200 pixels to the inch.
        artist = basemap(source=spec, zoom=-6)
        self.assertEqual((artist.get_array().shape, pixel(artist, *CORNER)), ((800, 800, 4), BLACK))
        # pixel_ratio sets the resolution only.
        artist = basemap(source=spec, zoom=6, pixel_ratio=0.25)
        self.assertEqual((artist.get_array().shape, pixel(artist, *CORNER)), ((192, 192, 4), GREEN))
        for zoom in ["4", None, True]:
            with self.subTest(zoom=zoom), self.assertRaises(TypeError):
                basemap(source=spec, zoom=zoom)

    def test_crs(self):
        import pyproj

        # The square in degrees, in UTM zone 33N (in feet, too), with the CRS as a string, PROJJSON
        # or a pyproj.CRS, 5 degrees or 400 km wide: zoom 6 is MapLibre's zoom 5 whatever the unit.
        utm = pyproj.CRS("EPSG:32633")
        feet = pyproj.CRS("+proj=utm +zone=33 +units=us-ft")

        def center(crs):
            return pyproj.Transformer.from_crs(4326, crs, always_xy=True).transform(15, 45)

        cases = [
            ("EPSG:4326", (15, 45), 5),
            (utm, center(utm), 400_000),
            (utm.to_json_dict(), center(utm), 400_000),
            (feet, center(feet), 400_000 / feet.axis_info[0].unit_conversion_factor),
        ]
        for crs, (x, y), size in cases:
            with self.subTest(crs=pyproj.CRS(crs).name):
                extent = (x - size / 2, x + size / 2, y - size / 2, y + size / 2)
                ax = axes(extent)
                artist = basemap(ax, source=style(background=ZOOMS), crs=crs, zoom=6)
                self.assertEqual(ax.axis(), extent)
                np.testing.assert_allclose(artist.get_extent(), extent)
                self.assertEqual(pixel(artist, x, y), RED)
                self.assertEqual(
                    pixel(artist, extent[0] + 1e-3 * size, extent[2] + 1e-3 * size), GREEN
                )

    def test_stretched_latitudes(self):
        # Square axes showing 10 x 5 degrees (latitudes stretched twice, as GeoPandas does at 60
        # degrees): the image has square pixels on screen, and its zoom is that of the longitudes
        # (384 CSS pixels for 10 degrees: 4.75).
        extent = (10, 20, 42.5, 47.5)
        artist = basemap(
            axes(extent), source=style(background=ZOOMS), crs="EPSG:4326", attribution=False
        )
        np.testing.assert_allclose(artist.get_extent(), extent)
        self.assertEqual(artist.get_array().shape, (800, 800, 4))
        self.assertEqual(
            [pixel(artist, *point) for point in [(16.9, 46.4), (17.1, 46.6)]], [RED, GREEN]
        )

    def test_layout(self):
        # The size of the axes as drawn: after the layout engine of the figure and the aspect (2 x 1
        # here).
        extent = (EXTENT[0], EXTENT[1], CENTER[1] - HALF / 2, CENTER[1] + HALF / 2)
        figure = plt.figure(figsize=(4, 4), dpi=96, layout="constrained")
        ax = figure.add_subplot(aspect="equal")
        ax.axis(extent)
        height, width = basemap(ax, source=STYLE).get_array().shape[:2]
        figure.draw_without_rendering()
        box = ax.get_window_extent()
        # Within a CSS pixel (200 / 96 pixels): the short side is drawn in whole CSS pixels.
        size = (200 / 96 * box.width, 200 / 96 * box.height)
        np.testing.assert_allclose((width, height), size, atol=200 / 96)
        ax = axes(extent)
        ax.set_aspect("equal")
        self.assertEqual(basemap(ax, source=STYLE).get_array().shape, (400, 800, 4))

    def test_historical(self):
        # A style of OpenHistoricalMap's tiles (unused here) is drawn as of today: a square of 1800
        # to 1900 is not.
        async def missing(url):
            return None

        # The square's layer without a filter, with one in legacy syntax and one in expression
        # syntax.
        tiles = {
            "type": "vector",
            "tiles": ["https://vtiles.openhistoricalmap.org/maps/ohm/{z}/{x}/{y}.pbf"],
        }
        for layer_filter in [
            None,
            ["==", "$type", "Polygon"],
            ["==", ["geometry-type"], "Polygon"],
        ]:
            for end, color in [(1900.0, WHITE), (3000.0, RED)]:
                spec = style()
                spec["sources"]["ohm"] = tiles
                spec["sources"]["square"]["data"]["properties"] = {
                    "start_decdate": 1800.0,
                    "end_decdate": end,
                }
                if layer_filter is not None:
                    spec["layers"][1]["filter"] = layer_filter
                with self.subTest(layer_filter=layer_filter, end=end):
                    self.assertEqual(pixel(basemap(source=spec, load=missing), *CENTER), color)

    def test_extent_and_aspect(self):
        ax = axes()
        ax.set_aspect(2)
        basemap(ax, source=STYLE, reset_extent=False)
        self.assertEqual((ax.axis(), ax.get_aspect()), (EXTENT, 2))
        # An aspect for imshow, as in contextily.
        basemap(ax, source=STYLE, aspect="auto")
        self.assertEqual(ax.get_aspect(), "auto")
        # Inverted axes keep their direction; the image is still drawn north up.
        inverted = (EXTENT[1], EXTENT[0], EXTENT[2], EXTENT[3])
        ax = axes(inverted)
        artist = basemap(ax, source=STYLE)
        self.assertEqual(ax.axis(), inverted)
        np.testing.assert_allclose(artist.get_extent(), EXTENT)

    def test_imshow_args_and_labels(self):
        ax = axes()
        artist = basemap(ax, source=STYLE, interpolation="nearest", alpha=0.5, zorder=-1)
        self.assertEqual(
            (artist.get_interpolation(), artist.get_alpha(), artist.get_zorder()),
            ("nearest", 0.5, -1),
        )
        # Labels only: an overlay above the data (no symbol layer here, so nothing is drawn).
        overlay = basemap(ax, source=STYLE, labels="only")
        self.assertEqual(overlay.get_zorder(), 4)
        self.assertFalse(np.asarray(overlay.get_array())[:, :, 3].any())
        self.assertEqual(basemap(ax, source=STYLE, labels="only", zorder=2).get_zorder(), 2)
        overlay = basemap(ax, source=STYLE, labels="only", labels_zorder=2.5)
        self.assertEqual(overlay.get_zorder(), 2.5)
        self.assertEqual(basemap(ax, source=STYLE, labels=False).get_zorder(), 0)
        with self.assertRaises(ValueError):
            basemap(ax, source=STYLE, labels="none")
        # contextily's warping of raster tiles does not apply: ignored.
        with self.assertWarnsRegex(UserWarning, "resampling is ignored"):
            self.assertEqual(pixel(basemap(ax, source=STYLE, resampling="nearest"), *CENTER), RED)

    def test_labels_above(self):
        # Blue icons (a symbol layer) at the center, from a source of their own and from one that a
        # line layer draws too.
        image = io.BytesIO()
        plt.imsave(image, np.full((32, 32, 4), BLUE, np.uint8), format="png")
        sprite = {"dot": {"x": 0, "y": 0, "width": 32, "height": 32, "pixelRatio": 1}}
        point = {"type": "Point", "coordinates": [15, 45]}
        dots = {"type": "Feature", "properties": {}, "geometry": point}
        files = {
            "https://example.com/sprite.json": json.dumps(sprite).encode(),
            "https://example.com/sprite.png": image.getvalue(),
            "https://example.com/sprite@2x.json": json.dumps(sprite).encode(),
            "https://example.com/sprite@2x.png": image.getvalue(),
            "https://example.com/dots.json": json.dumps(dots).encode(),
        }

        async def load(url):
            return files[url]

        spec = style(attribution="Square") | {"sprite": "https://example.com/sprite"}
        spec["sources"] |= {
            "shared": {"type": "geojson", "data": dots, "attribution": "Shared"},
            "dots": {
                "type": "geojson",
                "data": "https://example.com/dots.json",
                "attribution": "Dots",
            },
        }
        spec["layers"].append({"id": "line", "type": "line", "source": "shared"})
        for name in ["shared", "dots"]:
            layer = {"id": name, "type": "symbol", "source": name}
            spec["layers"].append({**layer, "layout": {"icon-image": "dot"}})

        def drawn(**options):
            ax = axes()
            bml.add_basemap(ax, source=spec, load=load, **options)
            return ax

        # The map, then its labels above the data (green, over all of the map).
        ax = axes()
        ax.axhspan(*EXTENT[2:], color="lime")
        bml.add_basemap(ax, source=spec, load=load, labels="above", attribution=False)
        ax.figure.canvas.draw()
        figure = np.asarray(ax.figure.canvas.buffer_rgba())
        self.assertEqual(figure[192, 192].tolist(), BLUE)
        self.assertEqual(figure[20, 20].tolist(), GREEN)
        below, above = ax.images
        self.assertEqual((below.get_zorder(), above.get_zorder()), (0, 4))
        self.assertEqual(pixel(below, *CENTER), RED)
        self.assertEqual(pixel(above, *CORNER)[3], 0)
        # Other arguments of imshow are those of both, but the zorder: that of the map.
        below, above = drawn(labels="above", alpha=0.5, zorder=-1).images
        self.assertEqual((below.get_alpha(), above.get_alpha()), (0.5, 0.5))
        self.assertEqual((below.get_zorder(), above.get_zorder()), (-1, 4))
        below, above = drawn(labels="above", labels_zorder=8).images
        self.assertEqual((below.get_zorder(), above.get_zorder()), (0, 8))
        # Above the data and below the legends of matplotlib.
        ax = axes()
        line = ax.plot(*CENTER, "o", label="data")[0]
        bml.add_basemap(ax, source=spec, load=load, labels="above")
        zorders = [line.get_zorder(), ax.images[1].get_zorder(), ax.legend().get_zorder()]
        self.assertEqual(zorders, sorted(set(zorders)))
        self.assertGreater(ax.inset_axes((0, 0, 1, 1)).get_zorder(), ax.images[1].get_zorder())
        # One attribution, as of the whole style.
        for labels in [True, "above"]:
            texts = [text.get_text() for text in drawn(labels=labels).texts]
            self.assertEqual(texts, ["Square | Shared | Dots"])
        # Nothing is drawn if the labels cannot be.
        del files["https://example.com/dots.json"]
        ax = axes()
        with self.assertRaises(KeyError):
            bml.add_basemap(ax, source=spec, load=load, labels="above")
        self.assertEqual((len(ax.images), len(ax.texts)), (0, 0))

    def test_attribution(self):
        def texts(**options):
            ax = axes()
            basemap(ax, source=style(attribution="Square"), **options)
            return [(text.get_text(), text.get_size()) for text in ax.texts]

        self.assertEqual(texts(), [("Square", 8)])
        self.assertEqual(texts(attribution=True), [("Square", 8)])
        self.assertEqual(texts(attribution="custom text"), [("custom text", 8)])
        self.assertEqual(texts(attribution=False), [])
        self.assertEqual(texts(attribution_size=12), [("Square", 12)])
        # In matplotlib's default font, backed up by installed fonts of Chinese, Japanese and
        # Korean.
        family = bml.add_attribution(axes(), "地理院").get_fontfamily()
        self.assertEqual(family[: len(plt.rcParams["font.family"])], plt.rcParams["font.family"])
        # Above the legend, the images of the basemap and those drawn before.
        ax = axes()
        for options, expected in [
            ({}, 10),
            ({"labels": "above", "labels_zorder": 9.5}, 10.5),
            ({"zorder": 20}, 21),
            ({"zorder": 12}, 21),
        ]:
            basemap(ax, source=style(attribution="Square"), **options)
            self.assertEqual([text.get_zorder() for text in ax.texts], [expected])
        self.assertGreater(10, ax.legend([]).get_zorder())
        # Basemaps drawn over one another share one attribution.
        ax = axes()
        basemap(ax, source=style(attribution="Square"))
        basemap(ax, source=style(attribution="Terrain"))
        basemap(ax, source=style(attribution="Square"), labels="only")
        self.assertEqual([text.get_text() for text in ax.texts], ["Square | Terrain"])
        # Only the sources drawn: not one no layer uses or only a hidden one, nor that of the labels
        # with labels=False.
        spec = style(attribution="Square")
        empty = {"type": "FeatureCollection", "features": []}
        spec["sources"] |= {
            name: {"type": "geojson", "data": empty, "attribution": name}
            for name in ["Names", "Unused", "Hidden"]
        }
        spec["layers"].append({"id": "names", "type": "symbol", "source": "Names"})
        spec["layers"].append(
            {"id": "hidden", "type": "line", "source": "Hidden", "layout": {"visibility": "none"}}
        )
        for labels, expected in [(True, "Square | Names"), (False, "Square")]:
            ax = axes()
            basemap(ax, source=spec, labels=labels)
            self.assertEqual([text.get_text() for text in ax.texts], [expected])
        # And the style's own.
        ax = axes()
        basemap(
            ax,
            source=spec | {"attribution": "<a href='https://style.example'>Style</a>"},
            labels=False,
        )
        self.assertEqual([text.get_text() for text in ax.texts], ["Style | Square"])

    def test_add_attribution(self):
        ax = axes()
        text = bml.add_attribution(ax, "Test")
        self.assertEqual(
            (text.get_text(), text.get_size(), text.get_ha(), list(ax.texts)),
            ("Test", 8, "right", [text]),
        )
        self.assertEqual(bml.add_attribution(axes(), "Test", zorder=5).get_zorder(), 5)
        # In the bottom right corner of the axes.
        ax.figure.canvas.draw()
        box = text.get_bbox_patch().get_window_extent()
        self.assertAlmostEqual(box.x1, 384, delta=1)
        self.assertAlmostEqual(box.y0, 0, delta=1)
        # kwargs over the defaults, under any of matplotlib's names.
        for kwargs in [
            {"font_size": 15, "fontfamily": "monospace", "ha": "left", "va": "top"},
            {
                "fontsize": 15,
                "family": "monospace",
                "horizontalalignment": "left",
                "verticalalignment": "top",
            },
        ]:
            with self.subTest(**kwargs):
                text = bml.add_attribution(ax, "Test", **kwargs)
                properties = (text.get_size(), text.get_fontfamily(), text.get_ha(), text.get_va())
                self.assertEqual(properties, (15, ["monospace"], "left", "top"))

    def test_long_attribution(self):
        # Axes with margins: the text is wrapped to their width, again when the figure is resized.
        figure = plt.figure(figsize=(4, 4), dpi=96)
        ax = figure.add_axes((0.2, 0.1, 0.6, 0.8))
        text = bml.add_attribution(ax, " ".join(["© OpenStreetMap contributors"] * 6))
        for width, lines in [(4, 4), (2, 10)]:
            figure.set_size_inches(width, 4)
            figure.canvas.draw()
            box, inside = text.get_bbox_patch().get_window_extent(), ax.get_window_extent()
            self.assertGreaterEqual(text.get_text().count("\n") + 1, lines)
            self.assertTrue(
                inside.x0 - 0.5 <= box.x0
                and box.x1 <= inside.x1 + 0.5
                and inside.y0 - 0.5 <= box.y0
            )


def zoomed(factor, extent=EXTENT):
    """`extent` around its center, `factor` times as wide and high."""
    left, right, bottom, top = extent
    (x, y), (width, height) = ((left + right) / 2, (bottom + top) / 2), (right - left, top - bottom)
    half = factor * width / 2, factor * height / 2
    return (x - half[0], x + half[0], y - half[1], y + half[1])


class DrawTest(unittest.TestCase):
    """Basemaps are rendered anew for the axes as they are drawn."""

    def tearDown(self):
        plt.close("all")

    def shape(self, artist, **options):
        """The shape of the image drawn: on the screen, or saved with options of `savefig`."""
        figure = artist.axes.figure
        if options:
            figure.savefig(io.BytesIO(), **options)
        else:
            figure.canvas.draw()
        return artist.get_array().shape[:2]

    def test_unchanged(self):
        artist = basemap(source=STYLE)
        image = artist.get_array()
        for options in [{}, {"dpi": 100}, {"dpi": 200}, {"format": "pdf"}, {"format": "svg"}]:
            with self.subTest(**options):
                self.assertEqual(self.shape(artist, **options), (800, 800))
                self.assertIs(artist.get_array(), image)

    def test_resolution(self):
        # That of the figure as drawn, 200 pixels to the inch or more.
        for options in [{}, {"interpolation": "none"}]:
            artist = basemap(source=STYLE, **options)
            for form in ["png", "pdf", "svg"]:
                with self.subTest(form=form, **options):
                    self.assertEqual(self.shape(artist, format=form, dpi=300), (1200, 1200))
                    self.assertEqual(self.shape(artist), (800, 800))
        # With two images, which vector graphics draw as one.
        basemap(artist.axes, source=STYLE)
        self.assertEqual(self.shape(artist, format="pdf", dpi=300), (1200, 1200))
        # pixel_ratio is kept.
        artist = basemap(source=STYLE, pixel_ratio=1)
        self.assertEqual(self.shape(artist, dpi=300), (384, 384))
        # As is the map: its zoom, which is automatic (4) or given (contextily's 6 is 5).
        for zoom, color in [("auto", RED), (6, GREEN)]:
            artist = basemap(source=style(background=ZOOMS), zoom=zoom)
            self.assertEqual(self.shape(artist, dpi=300), (1200, 1200))
            self.assertEqual(pixel(artist, *CORNER), color)

    def test_size(self):
        artist = basemap(source=STYLE)
        artist.axes.set_aspect("equal")
        artist.axes.figure.set_size_inches(2, 1)
        self.assertEqual(self.shape(artist), (200, 200))
        # The zoom of an automatic one follows (MapLibre's 3), one given does not.
        for zoom, color in [("auto", BLACK), (6, GREEN)]:
            artist = basemap(source=style(background=ZOOMS), zoom=zoom)
            artist.axes.figure.set_size_inches(2, 2)
            self.assertEqual(self.shape(artist), (400, 400))
            self.assertEqual(pixel(artist, *CORNER), color)
        # Axes smaller than a pixel (a tiny window) are drawn with the image there was.
        artist.axes.set_position((0, 0, 1, 1e-3))
        self.assertEqual(self.shape(artist), (400, 400))

    def test_limits(self):
        # The zoom follows the limits, so labels keep their size: an automatic one (4) and one given
        # (contextily's 6 is 5) are 1 more in half the extent.
        for zoom, colors in [("auto", [GREEN, BLACK]), (6, [BLUE, RED])]:
            artist = basemap(source=style(background=ZOOMS), zoom=zoom)
            ax = artist.axes
            limits = ax.dataLim.frozen().extents
            for factor, color in zip([0.5, 2], colors, strict=True):
                extent = zoomed(factor)
                ax.axis(extent)
                with self.subTest(zoom=zoom, factor=factor):
                    self.assertEqual(self.shape(artist), (800, 800))
                    self.assertEqual(ax.axis(), extent)
                    self.assertEqual(artist.get_extent(), extent)
                    self.assertEqual(pixel(artist, extent[0], extent[3]), color)
            # The limits of the data are those of the basemap added.
            np.testing.assert_array_equal(ax.dataLim.extents, limits)
        # Beyond the map, and inverted.
        ax.axis((EXTENT[1] + 10 * TURN, EXTENT[0] + 10 * TURN, *EXTENT[2:]))
        self.assertEqual(self.shape(artist), (800, 800))

    def test_crs(self):
        # In the CRS given, stretched as drawn.
        extent = (10, 20, 42.5, 47.5)
        artist = basemap(axes(extent), source=STYLE, crs="EPSG:4326")
        artist.axes.axis(zoomed(0.8, extent))
        self.assertEqual(self.shape(artist), (800, 800))
        self.assertEqual(
            [pixel(artist, *point) for point in [(16.9, 46.4), (17.1, 46.6)]], [RED, WHITE]
        )
        artist.axes.figure.set_size_inches(4, 2)
        self.assertEqual(self.shape(artist), (400, 800))

    def test_labels_above(self):
        ax = axes()
        bml.add_basemap(ax, source=STYLE, labels="above")
        ax.axis(zoomed(2))
        for artist in ax.images:
            self.assertEqual(self.shape(artist, dpi=300), (1200, 1200))
            self.assertEqual(artist.get_extent(), zoomed(2))

    def test_layout(self):
        # A layout made after the basemap, by the figure or the caller.
        def check(artist):
            height, width = self.shape(artist)
            box = artist.axes.get_window_extent()
            self.assertAlmostEqual(box.width, box.height)
            np.testing.assert_allclose((width, height), 200 / 96 * box.width, atol=1)

        for layout in ["constrained", None]:
            with self.subTest(layout=layout):
                figure, axs = plt.subplots(1, 2, figsize=(4, 4), dpi=96, layout=layout)
                for ax in axs:
                    ax.axis(EXTENT)
                    ax.set_aspect("equal")
                artist = basemap(axs[0], source=STYLE)
                image = artist.get_array()
                figure.suptitle("Title")
                axs[1].set_ylabel("Label")
                # Adding another does not render it: drawing does.
                basemap(axs[1], source=STYLE)
                self.assertIs(artist.get_array(), image)
                if layout is None:
                    figure.tight_layout()
                check(artist)
                self.assertIsNot(artist.get_array(), image)

    def test_attribution(self):
        # That of a source shown by zooming in is added.
        async def load(url):
            if url.endswith(".json"):
                tiles = ["https://example.com/{z}/{x}/{y}.pbf"]
                return json.dumps({"tiles": tiles, "attribution": url[-6]}).encode()
            return None

        sources = {
            name: {"type": "vector", "url": f"https://example.com/{name}.json"} for name in "AB"
        }
        layers = [
            {"id": name, "type": "line", "source": name, "source-layer": "x", "minzoom": minzoom}
            for name, minzoom in [("A", 0), ("B", 4.5)]
        ]
        spec = {"version": 8, "sources": sources, "layers": layers}
        for attribution, expected in [
            (None, [["A"], ["A | B"]]),
            ("custom", [["custom"], ["custom"]]),
            (False, [[], []]),
        ]:
            ax = axes()
            artist = basemap(ax, source=spec, load=load, attribution=attribution)
            texts = []
            for extent in [EXTENT, zoomed(0.5)]:
                ax.axis(extent)
                self.shape(artist)
                texts.append([text.get_text() for text in ax.texts])
            self.assertEqual(texts, expected)

    def test_pan(self):
        # Dragged, the image moves with the axes: it is rendered when dropped.
        artist = basemap(source=STYLE)
        ax, image = artist.axes, artist.get_array()
        ax.start_pan(192, 192, 1)
        ax.drag_pan(1, None, 292, 192)
        self.shape(artist)
        self.assertIs(artist.get_array(), image)
        np.testing.assert_allclose(artist.get_extent(), EXTENT)
        ax.end_pan()
        self.shape(artist)
        self.assertEqual(artist.get_extent(), ax.axis())
        self.assertEqual(pixel(artist, *CENTER), RED)

    def test_changed_style(self):
        # Changed by the caller since, as to draw another: drawn as it was given.
        spec = style()
        artist = basemap(source=spec)
        spec["layers"].pop()
        artist.axes.axis(zoomed(2))
        self.shape(artist)
        self.assertEqual(pixel(artist, *CENTER), RED)

    def test_errors(self):
        # Raised, leaving the image as it was; the next drawing tries again.
        async def load(url):
            if broken:
                raise OSError(url)
            return json.dumps(STYLE["sources"]["square"]["data"]).encode()

        broken = False
        spec = style()
        spec["sources"]["square"]["data"] = "https://example.com/square.json"
        artist = basemap(source=spec, load=load)
        image = artist.get_array()
        artist.axes.axis(zoomed(2))
        broken = True
        for _ in range(2):
            with self.assertRaises(OSError):
                self.shape(artist)
            self.assertIs(artist.get_array(), image)
            np.testing.assert_allclose(artist.get_extent(), EXTENT)
        broken = False
        self.assertEqual(self.shape(artist), (800, 800))
        self.assertEqual(artist.get_extent(), zoomed(2))

    def test_pickle(self):
        # The copy keeps the image it has (the loader, a local function, is not pickled).
        async def load(url):
            return None

        artist = basemap(source=STYLE, load=load)
        [copy] = pickle.loads(pickle.dumps(artist.axes.figure)).axes[0].images
        copy.axes.axis(zoomed(2))
        self.assertEqual(self.shape(copy, dpi=300), (800, 800))
        self.assertEqual(copy.get_extent(), artist.get_extent())


class ContextilyTest(unittest.TestCase):
    """Sources that are not MapLibre styles go to contextily."""

    def tearDown(self):
        plt.close("all")

    def test_other_sources(self):
        calls = []
        stub = types.ModuleType("contextily")
        stub.add_basemap = lambda ax, **options: calls.append((ax, options))
        ax = axes()
        tiles = "https://tile.example/{z}/{x}/{y}.png"
        with mock.patch.dict(sys.modules, {"contextily": stub}):
            for source in ["OpenStreetMap.Mapnik", tiles, {"url": tiles}, Path("map.tif")]:
                with self.subTest(source=source):
                    with self.assertWarnsRegex(UserWarning, "contextily.add_basemap"):
                        bml.add_basemap(ax, 5, source, crs="EPSG:4326", resampling=1, alpha=0.5)
                    # Every option given; None, contextily's default too, is left out.
                    options = {
                        "zoom": 5,
                        "source": source,
                        "interpolation": "bilinear",
                        "attribution_size": 8,
                    }
                    options |= {
                        "reset_extent": True,
                        "crs": "EPSG:4326",
                        "resampling": 1,
                        "alpha": 0.5,
                    }
                    self.assertEqual(calls.pop(), (ax, options))
            # basemaplibre's own options do not apply to them.
            for options in [{"labels": False}, {"pixel_ratio": 2}, {"load": print}]:
                with self.subTest(**options), self.assertRaises(TypeError):
                    bml.add_basemap(ax, source=tiles, **options)
        self.assertEqual(calls, [])

    def test_misspelled_style(self):
        misspelled = self.assertRaisesRegex(ValueError, "did you mean 'OpenFreeMap.Liberty'")
        with mock.patch.dict(sys.modules, {"xyzservices": None}), misspelled:
            bml.add_basemap(axes(), source="OpenFreeMap.liberty")

    def test_without_contextily(self):
        with (
            mock.patch.dict(sys.modules, {"contextily": None}),
            self.assertRaises(ImportError) as raised,
        ):
            bml.add_basemap(axes(), source="OpenStreetMap.Mapnik")
        self.assertEqual(raised.exception.name, "contextily")
        self.assertIn("pip install contextily", str(raised.exception))


class RunningLoopTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        plt.close("all")

    async def test_in_event_loop(self):
        # As in Jupyter, where an event loop runs: the render runs in a thread of its own.
        self.assertEqual(pixel(basemap(source=STYLE), *CENTER), RED)

    async def test_custom_load(self):
        loaded = []

        async def load(url):
            loaded.append(url)
            return json.dumps(STYLE).encode() if url == "test://style.json" else None

        artist = basemap(source="test://style.json", load=load)
        self.assertEqual((loaded, pixel(artist, *CENTER)), (["test://style.json"], RED))

    async def test_interrupt(self):
        # Interrupting the wait (Ctrl-C in Jupyter) cancels the render in its thread.
        started, cancelled = Event(), Event()

        async def slow():
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def interrupted(future, timeout=None):
            started.wait(5)
            raise KeyboardInterrupt

        with (
            mock.patch.object(concurrent.futures.Future, "result", interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            _render.run(slow())
        self.assertTrue(cancelled.is_set())


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.path, self.headers))
                # /flaky/ fails twice (HTTP 503, then 429), /broken/ always.
                failures = [path for path, _ in cls.requests].count(self.path) - 1
                if (
                    self.path.startswith("/broken/")
                    or self.path.startswith("/flaky/")
                    and failures < 2
                ):
                    self.send_error(503 if failures == 0 else 429)
                    return
                if self.path.endswith("/style.json"):
                    vector = {"type": "vector", "url": f"{cls.base}/tilejson.json"}
                    layer = {"id": "v", "type": "line", "source": "vector", "source-layer": "roads"}
                    spec = {
                        **STYLE,
                        "sources": {**STYLE["sources"], "vector": vector},
                        "layers": [*STYLE["layers"], layer],
                    }
                    data = json.dumps(spec).encode()
                elif self.path == "/tilejson.json":
                    tiles = [f"{cls.base}/vector/{{z}}/{{x}}/{{y}}.pbf"]
                    data = json.dumps(
                        {"tiles": tiles, "maxzoom": 0, "attribution": "<b>Vector</b>"}
                    ).encode()
                elif self.path.startswith("/vector/"):
                    data = b""  # an empty vector tile
                else:
                    self.send_error(
                        {"/missing.json": 404, "/out-of-range.json": 400}.get(self.path, 403)
                    )
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        # Each test with a cache of its own.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(_render, "_cache_dir", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.requests.clear()

    def tearDown(self):
        plt.close("all")

    def test_style_url(self):
        self.requests.clear()
        ax = axes()
        artist = basemap(
            ax, source=f"{self.base}/style.json", headers={"X-Key": "k", "user-agent": "me"}
        )
        self.assertEqual(pixel(artist, *CENTER), RED)
        # The attribution of the TileJSON, and the headers on every request.
        self.assertEqual([text.get_text() for text in ax.texts], ["Vector"])
        paths = [path for path, _ in self.requests]
        self.assertIn("/tilejson.json", paths)
        self.assertIn("/vector/0/0/0.pbf", paths)
        for path, headers in self.requests:
            self.assertEqual((headers.get("X-Key"), headers.get("User-Agent")), ("k", "me"), path)
        self.requests.clear()
        basemap(source=f"{self.base}/style.json", timeout=(5, 10))
        self.assertTrue(
            all(headers["User-Agent"].startswith("basemaplibre ") for _, headers in self.requests)
        )

    def test_cache(self):
        def paths():
            return sorted(path for path, _ in self.requests)

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory, "cache")
            bml.set_cache_dir(cache)
            basemap(source=f"{self.base}/style.json")
            fetched = paths()
            self.assertIn("/vector/0/0/0.pbf", fetched)
            # All but the style and its TileJSON, which name the current tiles.
            self.assertEqual(len(list(cache.iterdir())), len(fetched) - 2)
            # Again: those two from the server, the rest from the cache; with other headers, all
            # from the server.
            self.requests.clear()
            self.assertEqual(pixel(basemap(source=f"{self.base}/style.json"), *CENTER), RED)
            self.assertEqual(paths(), ["/style.json", "/tilejson.json"])
            self.requests.clear()
            basemap(source=f"{self.base}/style.json", headers={"X-Key": "k"})
            self.assertEqual(paths(), fetched)
            # HTTP 404 is not kept.
            with self.assertRaises(ValueError):
                basemap(source=f"{self.base}/missing.json")
            self.assertEqual(len(list(cache.iterdir())), 2 * (len(fetched) - 2))

    def test_redraw(self):
        # A basemap fetches its style and TileJSON once, however many times it is rendered.
        artist = basemap(source=f"{self.base}/style.json", labels="above")
        artist.axes.axis(zoomed(2))
        artist.axes.figure.canvas.draw()
        self.assertEqual(artist.get_extent(), zoomed(2))
        paths = [path for path, _ in self.requests]
        self.assertEqual([paths.count(path) for path in ["/style.json", "/tilejson.json"]], [1, 1])

    def test_timeout(self):
        # None is no time limit, as in contextily.
        cases = [
            (None, httpx.Timeout(None)),
            (3, httpx.Timeout(3)),
            ((5, 10), httpx.Timeout(10, connect=5)),
        ]
        for timeout, expected in cases:
            client = _render._client(None, timeout)
            self.assertEqual(client.timeout, expected)
            asyncio.run(client.aclose())

    @mock.patch.object(_render, "_BACKOFF", 0)
    def test_retries(self):
        def attempts(path):
            return [requested for requested, _ in self.requests].count(path)

        # HTTP 503 and 429 are retried twice; the third failure raises.
        self.assertEqual(pixel(basemap(source=f"{self.base}/flaky/style.json"), *CENTER), RED)
        self.assertEqual(attempts("/flaky/style.json"), 3)
        with self.assertRaises(httpx.HTTPStatusError):
            basemap(source=f"{self.base}/broken/style.json")
        self.assertEqual(attempts("/broken/style.json"), 3)
        # Other HTTP errors are not retried; 404 and 400 (a WMTS tile out of range) are a missing
        # resource.
        with self.assertRaises(httpx.HTTPStatusError):
            basemap(source=f"{self.base}/bad.json")
        for path in ["/missing.json", "/out-of-range.json"]:
            with self.assertRaises(ValueError):
                basemap(source=f"{self.base}{path}")
        self.assertEqual(
            [attempts(path) for path in ["/bad.json", "/missing.json", "/out-of-range.json"]],
            [1, 1, 1],
        )
        # Network errors and timeouts are retried too; a URL HTTPX cannot fetch (s3://) is not.
        errors = [
            (httpx.ConnectError("refused"), 3),
            (httpx.ReadTimeout("slow"), 3),
            (httpx.UnsupportedProtocol("s3"), 1),
        ]
        for error, tries in errors:
            with (
                self.subTest(error=error),
                mock.patch.object(httpx.AsyncClient, "get", side_effect=error) as get,
            ):
                with self.assertRaises(type(error)):
                    basemap(source=f"{self.base}/style.json")
                self.assertEqual(get.await_count, tries)


if __name__ == "__main__":
    unittest.main()
