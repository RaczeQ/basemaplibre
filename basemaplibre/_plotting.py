"""Basemaps and attributions on matplotlib axes."""

import copy
import importlib
import reprlib
import warnings
from functools import partial
from typing import TYPE_CHECKING, Any

from matplotlib import cbook
from matplotlib.text import Text

from basemaplibre._attribution import PAD, Attribution, font_family
from basemaplibre._image import BasemapImage, Framing
from basemaplibre._render import (
    Loader,
    Timeout,
    Zoom,
    attribution_text,
    check_zoom,
    crs_of,
    render,
)
from basemaplibre._source import Labels, Source, misspelled, resolve

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.text import Annotation

ATTRIBUTION_SIZE = 8
# Above the data, whose zorder is 1 to 3 by default.
_LABELS_ZORDER = 9


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

    The image covers the extent of the axes exactly, at the resolution of the figure. It is rendered
    here, so that errors are raised, and again whenever the axes are drawn with other limits, at
    another size or at another resolution: after zooming, panning or `fig.tight_layout()`, or by
    `fig.savefig(dpi=300)`. That may download tiles, and raises its errors where the figure is
    drawn.

    Styles of OpenHistoricalMap's tiles are drawn as of today, as on its website.

    Failed requests (network errors, timeouts, HTTP 429 and 5xx) are tried twice more, after 1 and
    2 seconds. Downloads are cached on disk, by URL and `headers` (see `set_cache_dir`), but for the
    style and its TileJSON, which name the current tiles.

    Args:
        ax (Axes): Axes to draw on, with their extent in `crs`.
        zoom (float | "auto", optional): Level of detail as in contextily: the zoom of 256-pixel XYZ
            tiles of the same scale, which may be fractional (the style is evaluated at MapLibre
            zoom `zoom - 1`), for the limits the axes have now. "auto" draws the style at its size
            on a web page (96 CSS pixels to the inch of the figure). Either follows the axes as they
            are zoomed. Defaults to "auto".
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
        labels (bool | "only" | "above", optional): Whether to draw the style's symbol layers
            (labels and icons). "only" draws nothing else, as an overlay above the data (`zorder` 9
            unless given). "above" draws the rest under the data and the labels above it (at
            `zorder` 9, other arguments of `imshow` as given), in two images. Defaults to True.
        pixel_ratio (float, optional): Image pixels per CSS pixel, whatever the resolution of the
            figure; with `zoom="auto"`, `dpi / 96` is that of a figure of `dpi`. Defaults to None:
            the dpi the figure is drawn at, but 200 pixels to the inch at least, sharp on HiDPI
            screens.
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
    if (engine := figure.get_layout_engine()) is not None:
        engine.execute(figure)
    ax.apply_aspect()
    limits = ax.axis()
    framing = Framing(crs_of(crs), level, zoom_adjust or 0, pixel_ratio)
    view = framing.view(ax)
    if level is not None:
        # The zoom of these limits: with others, it changes as the automatic one does.
        framing = framing._replace(size=view.size)
    # All are rendered before one is drawn, so an error leaves no half of a basemap.
    parts: list[Labels] = [False, "only"] if labels == "above" else [labels]
    style = copy.deepcopy(style)  # the caller may change it before the axes are drawn
    kept: dict[str, bytes] = {}
    renders = [
        partial(render, style, labels=part, load=load, headers=headers, timeout=timeout, kept=kept)
        for part in parts
    ]
    rendered = [render_view(view.crs, view.box) for render_view in renders]
    if labels == "only":
        extra_imshow_args.setdefault("zorder", _LABELS_ZORDER)
    extra_imshow_args.setdefault("aspect", ax.get_aspect())  # imshow's default would make it equal
    images = []
    for rgba, _ in rendered:
        images.append(
            ax.imshow(rgba, extent=view.extent, interpolation=interpolation, **extra_imshow_args)
        )
        extra_imshow_args["zorder"] = _LABELS_ZORDER  # of the second image: "above", the labels
    if reset_extent:
        ax.axis(limits)
    own = attribution is None or attribution is True
    text = attribution_text(text for _, text in rendered) if own else attribution
    artist = _attribute(ax, str(text), attribution_size) if text else None
    for image, render_view in zip(images, renders, strict=True):
        BasemapImage.of(image, framing, view, render_view, artist if own else None)


def _attribute(ax: "Axes", text: str, font_size: float) -> "Annotation":
    """Add `text` to the attribution of `ax`, which the basemaps drawn over one another share."""
    drawn = [artist for artist in ax.texts if isinstance(artist, Attribution)]
    if not drawn:
        return add_attribution(ax, text, font_size=font_size)
    drawn[-1].set_text(attribution_text([drawn[-1].get_text(), text]))
    return drawn[-1]


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
