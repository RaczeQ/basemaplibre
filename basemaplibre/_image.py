"""The image of a basemap: a matplotlib image rendered for the axes as they are drawn."""

from typing import TYPE_CHECKING, Any, NamedTuple

from matplotlib.image import AxesImage
from ml2drender import ProjectedBox

from basemaplibre._render import Bbox, Crs, attribution_text, on_screen, projected_box

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np
    from matplotlib.axes import Axes
    from matplotlib.backend_bases import RendererBase
    from matplotlib.text import Text
    from numpy.typing import NDArray

    Render = Callable[[Crs, ProjectedBox], tuple[NDArray[np.uint8], str]]

# CSS pixels in an inch: with the automatic zoom, a style's 12 px text is 9 points high on paper.
_CSS_PER_INCH = 96
# The image's pixels per inch of the figure, at least: twice matplotlib's default dpi (about two per
# CSS pixel, as on HiDPI screens). Figures of that dpi are rendered once for both kinds of screens
# and for saving at up to twice their dpi.
_MIN_DPI = 200


class View(NamedTuple):
    """What axes show: their extent and what to render for it."""

    extent: Bbox  # (left, right, bottom, top), in the CRS of the axes
    size: int  # in CSS pixels, of the long side
    crs: Crs
    box: ProjectedBox

    @property
    def key(self) -> tuple[object, ...]:
        """What differs between the images of views."""
        return self.extent, self.size, self.box.pixels


class Framing(NamedTuple):
    """How to render what axes show."""

    crs: Crs
    zoom: float | None = None  # of 256-pixel XYZ tiles; None is automatic
    zoom_adjust: float = 0  # of the automatic zoom
    pixel_ratio: float | None = None  # None is the resolution of the figure
    size: int | None = None  # in CSS pixels, of the long side, instead of the zoom

    def view(self, ax: "Axes", magnification: float = 1.0) -> View:
        """
        Return the view of `ax`, whose size and limits are those drawn.

        `magnification` is the pixels drawn to one of the figure: more than one in vector graphics,
        which matplotlib draws at 72 dpi.
        """
        xmin, xmax, ymin, ymax = ax.axis()
        (left, right), (bottom, top) = sorted((xmin, xmax)), sorted((ymin, ymax))
        extent = (left, right, bottom, top)
        display, dpi = ax.get_window_extent(), ax.figure.dpi
        stretch = 1.0
        if display.width:
            stretch = display.height * (right - left) / (display.width * (top - bottom))
        crs, box = on_screen(self.crs, (left, bottom, right, top), stretch)
        width, height = box[2] - box[0], box[3] - box[1]
        # Pixels of the figure to the unit of the CRS.
        pixels = max(display.width / width, display.height / height)
        size = self.size
        if size is None:
            if self.zoom is None:
                scale = pixels * _CSS_PER_INCH / dpi * 2**self.zoom_adjust
            else:
                scale = 256 * 2**self.zoom / crs.units_per_turn
            # In whole CSS pixels (at least one): the scale drawn.
            size = max(1, round(max(width, height) * scale))
        ratio = self.pixel_ratio
        if ratio is None:
            ratio = pixels * max(width, height) / size * max(magnification, _MIN_DPI / dpi)
        return View(extent, size, crs, projected_box(box, size, ratio))


class BasemapImage(AxesImage):
    """
    An image rendered anew whenever its axes are drawn with another view.

    That is with other limits, at another size or at another resolution.
    """

    _framing: Framing
    _drawn: tuple[object, ...]  # the key of the view
    _render: "Render | None"  # None (of an unpickled figure) keeps the image
    _attribution: "Text | None"

    @classmethod
    def of(
        cls,
        image: AxesImage,
        framing: Framing,
        view: View,
        render: "Render",
        attribution: "Text | None",
    ) -> "BasemapImage":
        """
        Turn `image`, of `imshow` (which takes its many arguments), into a `BasemapImage` of `view`.

        As mplot3d does with the artists of the 2D methods. The attributions of other views are
        added to `attribution`, if any.
        """
        image.__class__ = cls
        assert isinstance(image, cls)
        image._framing, image._drawn = framing, view.key
        image._render, image._attribution = render, attribution
        return image

    def make_image(
        self, renderer: "RendererBase", magnification: float = 1.0, unsampled: bool = False
    ) -> Any:
        """Render the view of the axes, if another than the last, then make the image drawn."""
        # Here and not in draw, which vector graphics do not call for images drawn as one.
        self._update(renderer.get_image_magnification())
        return super().make_image(renderer, magnification, unsampled)

    def _update(self, magnification: float) -> None:
        display = self.axes.get_window_extent()
        # Not while dragged: the image moves with the axes (matplotlib has no public sign of it).
        dragged = hasattr(self.axes, "_pan_start")
        if self._render is None or dragged or min(display.width, display.height) < 1:
            return
        view = self._framing.view(self.axes, magnification)
        if view.key == self._drawn:
            return
        image, text = self._render(view.crs, view.box)
        self.set_data(image)
        self._extent = view.extent  # set_extent would change the limits of the axes and their data
        self._drawn = view.key
        if self._attribution is not None:
            self._attribution.set_text(attribution_text([self._attribution.get_text(), text]))

    def __getstate__(self) -> dict[str, Any]:
        """Return the state to pickle: without the loader, which may be a local function."""
        state: Any = super().__getstate__()
        return {**state, "_render": None}
