# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `labels_zorder` of `add_basemap`: the `zorder` of the labels drawn above the data
- `zorder` of `add_attribution`

### Changed

- The labels drawn above the data are below the legend and inset axes of matplotlib (`zorder` 4, it was 9)
- The attribution stays above basemaps and labels drawn at a `zorder` of 10 or above

## [0.1.0] - 2026-11-23

### Added

- `add_basemap`, `add_attribution`, `set_cache_dir` and `STYLES`, moved from `ml2drender.basemap`
- `labels="above"`: the map under the data and its labels above it, in one call
- Basemaps are rendered again when the axes are drawn with other limits, at another size or dpi

### Changed

- The image has 200 pixels to the inch of the figure at least (it had 192), so figures of the default dpi are rendered once for HiDPI screens too

### Fixed

- An attribution shared by two basemaps of the same axes was written twice

[Unreleased]: https://github.com/RaczeQ/basemaplibre/compare/0.1.0...HEAD

[0.1.0]: https://github.com/RaczeQ/basemaplibre/releases/tag/0.1.0
