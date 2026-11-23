"""
Basemaps for matplotlib and GeoPandas rendered from MapLibre styles.

The parameters are those of contextily's `add_basemap`, but the basemap is a MapLibre style (vector
tiles, labels, icons) rendered with ml2drender: for the extent of the axes, at their resolution and
directly in their CRS, instead of raster tiles that are merged and warped.
"""

from basemaplibre._plotting import add_attribution, add_basemap
from basemaplibre._render import set_cache_dir
from basemaplibre._source import STYLES

__version__ = "0.1.0"

__all__ = ["STYLES", "add_attribution", "add_basemap", "set_cache_dir"]
