"""Check that basic features work."""

if __name__ == "__main__":
    import matplotlib.pyplot as plt

    from basemaplibre import add_basemap

    fig, ax = plt.subplots()
    ax.axis((2300000, 2400000, 6800000, 6900000))
    layer = {"id": "red", "type": "background", "paint": {"background-color": "#ff0000"}}
    add_basemap(ax, source={"version": 8, "sources": {}, "layers": [layer]})

    if (ax.images[0].get_array() == [255, 0, 0, 255]).all():
        print("Smoke test succeeded")
    else:
        raise RuntimeError(f"Unexpected image: {ax.images[0].get_array()}")
