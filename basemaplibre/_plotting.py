"""Basemaps and attributions on matplotlib axes."""

import importlib
import reprlib
import warnings
from typing import TYPE_CHECKING, Any

from matplotlib import cbook
from matplotlib.text import Text

from basemaplibre._attribution import PAD, Attribution, font_family
from basemaplibre._render import (
    Loader,
    Timeout,
    Zoom,
    attribution_text,
    check_zoom,
    crs_of,
    on_screen,
    projected_box,
    render,
)
from basemaplibre._source import Labels, Source, misspelled, resolve

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.text import Annotation

ATTRIBUTION_SIZE = 8
# CSS pixels in an inch: with the automatic zoom, a style's 12 px text is 9 points high on paper.
_CSS_PER_INCH = 96
# The image's pixels per inch of the figure, at least (two per CSS pixel, as on HiDPI screens):
# figures of the default dpi get twice their resolution, sharp on those screens and saved at twice
# their dpi; figures of a higher dpi, theirs.
_MIN_DPI = 2 * _CSS_PER_INCH


def add_basemap(
    ax: "Axes",
    zoom: Zoom = "auto",
    source: Source | None = None,
    headers: dict[str, str] | None = None,
    interpolation: str = "bilinear",
    attribution: str | bool | None = None,
    attribution_size: float = ATTRIBUTION_SIZE,
    reset_extent: bool = True,
    crs: Any = None,
    resampling: Any = None,
    zoom_adjust: float | None = None,
    timeout: Timeout = None,
    *,
    labels: Labels = True,
    pixel_ratio: float | None = None,
    load: Loader | None = None,
    **extra_imshow_args: Any,
) -> None:
    """
    Draw a basemap rendered from a MapLibre style under the data of the axes.

    The parameters are those of contextily's `add_basemap`; `labels`, `pixel_ratio` and `load` are
    new. The style is drawn directly in `crs`, if ml2drender supports its projection. Axes that
    stretch the latitudes of a geographic CRS (as GeoPandas does) get the equidistant cylindrical
    projection they show, so labels keep their shape.

    The image covers the extent of the axes exactly. Their size is read as drawn (after the layout
    engine of the figure, such as `layout="constrained"`, and their aspect), but a layout made later
    (`fig.tight_layout()`) stretches the image: lay the figure out first.

    Styles of OpenHistoricalMap's tiles are drawn as of today, as on its website.

    Failed requests (network errors, timeouts, HTTP 429 and 5xx) are tried twice more, after 1 and
    2 seconds. Downloads are cached on disk, by URL and `headers` (see `set_cache_dir`), but for the
    style and its TileJSON, which name the current tiles.

    Args:
        ax (Axes): Axes to draw on, with their extent in `crs`.
        zoom (float | "auto", optional): Level of detail as in contextily: the zoom of 256-pixel XYZ
            tiles of the same scale, which may be fractional (the style is evaluated at MapLibre
            zoom `zoom - 1`). "auto" draws the style at its size on a web page (96 CSS pixels to the
            inch of the figure). Defaults to "auto".
        source (Source, optional): MapLibre style: a style dict, the URL of a style JSON, a name of
            `STYLES` or a local `.json` file. Any other source (a tile provider or its name, a URL
            of tiles, a raster file) is contextily's: it is drawn by `contextily.add_basemap` with
            a `UserWarning`. Defaults to None, which is "OpenFreeMap.Liberty".
        headers (dict[str, str], optional): HTTP headers sent with every request. Defaults to None.
        interpolation (str, optional): Interpolation of `imshow`. Defaults to "bilinear".
        attribution (str | bool, optional): Text in the corner, added to the one of a basemap drawn
            before. None and True are the attributions of the style and the sources it draws, False
            is none. Defaults to None.
        attribution_size (float, optional): Size of the attribution in points. Defaults to 8.
        reset_extent (bool, optional): Whether to keep the limits of the axes. Defaults to True.
        crs (Any, optional): CRS of the axes: anything `pyproj.CRS.from_user_input` reads, such as a
            GeoDataFrame's `crs`, "EPSG:4326" or a PROJJSON dict. Defaults to None, which is
            EPSG:3857 (Web Mercator).
        resampling (Any, optional): Ignored with a `UserWarning`: contextily's warping of raster
            tiles. Defaults to None.
        zoom_adjust (float, optional): Added to the zoom, "auto" too; may be fractional. Defaults to
            None.
        timeout (float | tuple[float, float], optional): Limit of each request in seconds, or of
            connecting and reading. Defaults to None, which is no limit as in contextily.
        labels (bool | "only", optional): Whether to draw the style's symbol layers (labels and
            icons). "only" draws nothing else, as an overlay above the data (`zorder` 9 unless
            given). Defaults to True.
        pixel_ratio (float, optional): Image pixels per CSS pixel; with `zoom="auto"`, `dpi / 96`
            matches a figure of `dpi`. Defaults to None: 192 pixels to the inch of the figure, or
            its dpi if higher, so figures of the default dpi get twice their resolution, for HiDPI
            screens and saving at twice their dpi.
        load (Loader, optional): Async `load(url)` that returns the bytes, or None for a missing
            resource. It replaces fetching over HTTP, and runs on a private event loop. Defaults to
            None.
        **extra_imshow_args (Any): Passed to `imshow`.

    Raises:
        ValueError: If `source` looks like a misspelled name of `STYLES`.
        ImportError: If `source` is contextily's and contextily is not installed.

    Examples:
        >>> import basemaplibre as bml
        >>> ax = gdf.plot(alpha=0.5)  # doctest: +SKIP
        >>> bml.add_basemap(ax, crs=gdf.crs, source="OpenFreeMap.Positron")  # doctest: +SKIP
    """
    style = resolve(source)
    if style is None:
        if (name := misspelled(source)) is not None:
            raise ValueError(
                f"{source!r} is neither a name of STYLES (did you mean {name!r}?)"
                " nor a source of contextily"
            )
        if labels is not True or pixel_ratio is not None or load is not None:
            raise TypeError(
                "labels, pixel_ratio and load apply to MapLibre styles only,"
                f" not to {reprlib.repr(source)}"
            )
        options = {
            "zoom": zoom,
            "headers": headers,
            "interpolation": interpolation,
            "attribution": attribution,
            "attribution_size": attribution_size,
            "reset_extent": reset_extent,
            "crs": crs,
            "resampling": resampling,
            "zoom_adjust": zoom_adjust,
            "timeout": timeout,
        }
        # None is contextily's default too: leave it out, for versions without headers or timeout.
        options = {key: value for key, value in options.items() if value is not None}
        _contextily(ax, source, options, extra_imshow_args)
        return
    if resampling is not None:
        warnings.warn(
            "resampling is ignored: styles are drawn in the CRS of the axes, not warped",
            stacklevel=2,
        )
    level = check_zoom(zoom, zoom_adjust)
    # The size and limits of ax as drawn: set by the layout engine of the figure (constrained,
    # tight) and the aspect.
    figure = ax.figure.figure
    if figure.get_layout_engine() is not None:
        figure.draw_without_rendering()
    ax.apply_aspect()
    xmin, xmax, ymin, ymax = ax.axis()
    (left, right), (bottom, top) = sorted((xmin, xmax)), sorted((ymin, ymax))
    extent = (left, right, bottom, top)
    display = ax.get_window_extent()
    stretch = 1.0
    if display.width:
        stretch = display.height * (right - left) / (display.width * (top - bottom))
    target, (left, bottom, right, top) = on_screen(crs_of(crs), (left, bottom, right, top), stretch)
    width, height = right - left, top - bottom
    if level is None:
        scale = _CSS_PER_INCH / ax.figure.dpi * max(display.width / width, display.height / height)
        scale *= 2 ** (zoom_adjust or 0)
    else:
        scale = 256 * 2**level / target.units_per_turn  # level: a zoom of 256-pixel XYZ tiles
    # The long side in whole CSS pixels (at least one): the scale drawn.
    size = max(1, round(max(width, height) * scale))
    if pixel_ratio is None:
        axes_ratio = max(display.width / width, display.height / height) * max(width, height) / size
        pixel_ratio = axes_ratio * max(1, _MIN_DPI / ax.figure.dpi)
    box = projected_box((left, bottom, right, top), size, pixel_ratio)
    image, text = render(style, target, box, labels, load, headers, timeout)
    if labels == "only":
        extra_imshow_args.setdefault("zorder", 9)
    extra_imshow_args.setdefault("aspect", ax.get_aspect())  # imshow's default would make it equal
    ax.imshow(image, extent=extent, interpolation=interpolation, **extra_imshow_args)
    if reset_extent:
        ax.axis((xmin, xmax, ymin, ymax))
    if attribution is None or attribution is True:
        attribution = text
    if attribution:
        # Basemaps drawn over one another (a hillshade over a map) share one attribution.
        drawn = [artist for artist in ax.texts if isinstance(artist, Attribution)]
        if drawn:
            drawn[-1].set_text(attribution_text([drawn[-1].get_text(), str(attribution)]))
        else:
            add_attribution(ax, str(attribution), font_size=attribution_size)


def _contextily(
    ax: "Axes", source: object, options: dict[str, Any], extra_imshow_args: dict[str, Any]
) -> None:
    """Draw `source`, which is not a MapLibre style, with `contextily.add_basemap`."""
    try:
        contextily = importlib.import_module("contextily")
    except ImportError as error:
        message = (
            f"source {reprlib.repr(source)} is not a MapLibre style. For raster tiles and files,"
            " install contextily (pip install contextily) and use contextily.add_basemap"
        )
        raise ImportError(message, name="contextily") from error
    warnings.warn(
        f"source {reprlib.repr(source)} is not a MapLibre style: drawn by contextily.add_basemap",
        stacklevel=3,
    )
    contextily.add_basemap(ax, source=source, **options, **extra_imshow_args)


def add_attribution(
    ax: "Axes", text: str, font_size: float = ATTRIBUTION_SIZE, **kwargs: Any
) -> "Annotation":
    """
    Write a text in the bottom right corner of the axes, as MapLibre's attribution control does.

    The text is on a translucent white box. Its words are wrapped to the width of the axes whenever
    the figure is drawn, and what still does not fit (a word wider than the axes) is clipped. The
    font is matplotlib's default, backed up by an installed font of Chinese, Japanese and Korean
    (Hiragino Sans, Yu Gothic, Noto Sans CJK JP, ...) for attributions in those.

    Args:
        ax (Axes): Axes to write on.
        text (str): Text to write.
        font_size (float, optional): Size of the text in points. Defaults to 8.
        **kwargs (Any): Passed to matplotlib's `Annotation`, over these defaults.

    Returns:
        Annotation: The text.

    Examples:
        >>> import basemaplibre as bml
        >>> import matplotlib.pyplot as plt
        >>> fig, ax = plt.subplots()
        >>> bml.add_attribution(ax, "© OpenStreetMap contributors").get_text()
        '© OpenStreetMap contributors'
    """
    # Under matplotlib's own names, which kwargs' aliases (fontsize for size, ha, ...) are turned
    # into.
    options: dict[str, Any] = {
        "xycoords": "axes fraction",
        "xytext": (-PAD * font_size, PAD * font_size),
        "textcoords": "offset points",
        "fontsize": font_size,
        "fontfamily": font_family(),
        "horizontalalignment": "right",
        "verticalalignment": "bottom",
        "zorder": 10,
        "clip_on": True,
        "parse_math": False,
        "bbox": {
            "boxstyle": f"square,pad={PAD}",
            "facecolor": "white",
            "alpha": 0.7,
            "edgecolor": "none",
        },
    }
    artist = Attribution(text, (1, 0), **(options | cbook.normalize_kwargs(kwargs, Text)))
    ax.add_artist(artist)
    return artist
