import math

def index_band_and_vis(index, satellite="sentinel2"):
    """Return band name(s) or single-band name and visualization dict for supported indices."""
    if index == "rgb":
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})
    elif index == "ndvi":
        # High-contrast NDVI palette: from bare soil (brown/red) to dense vegetation (dark green)
        return ("ndvi", {
            "min": -0.2, "max": 0.8,
            "discrete": True,
            "breaks": [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8],
            "palette": ['#8c2d04', '#d95f0e', '#feb24c', '#ffffbf', '#a1d99b', '#31a354', '#006837']
        })
    elif index == "ndwi":
        # Paleta más enfocada en agua: tonos tierra/seco -> amarillo claro -> azules (agua)
        # NDWI típicamente tiene valores negativos en suelos/vegetación y positivos para agua,
        # así que colocamos rupturas para resaltar valores positivos (agua) en azules intensos.
        return ("ndwi", {
            "min": -0.5,
            "max": 0.6,
            "discrete": True,
            "breaks": [-0.5, -0.2, 0.0, 0.2, 0.4],
            "palette": ['#7f3b08', '#fdb863', '#ffffbf', '#80b1d3', '#1f78b4', '#08306b']
        })
    elif index == "evi":
        # EVI: use a diverging-ish palette that separates low (stress) from healthy vegetation
        return ("evi", {"min": -0.2, "max": 0.6, "palette": ['#800026', '#bd0026', '#f46d43', '#fdae61', '#ffffbf', '#a6d96a', '#1a9641']})
    elif index == "savi":
        # SAVI: similar contrasting greens but biased to soil/veg separation
        return ("savi", {"min": -0.2, "max": 0.8, "palette": ['#8c2d04', '#d95f0e', '#feb24c', '#ffffbf', '#a1d99b', '#31a354', '#006837']})
    elif index == "ndmi":
        # NDMI (moisture) - strong blue -> red contrast
        return ("ndmi", {"min": -0.6, "max": 0.6, "discrete": True, "breaks": [-0.6, -0.2, 0.0, 0.2, 0.4, 0.6], "palette": ['#08306b', '#2171b5', '#6baed6', '#d9ef8b', '#fdae61', '#ec7014', '#b30000']})
    elif index == "gci":
        return ("gci", {"min": -0.5, "max": 1.5, "palette": ['#ffffe5', '#f7fcb9', '#c7e9c0', '#74c476', '#006d2c']})
    elif index == "vegetation_health":
        return ("vegetation_health", {"min": 0, "max": 1, "palette": ['#a50026', '#f46d43', '#fee08b', '#ffffbf', '#a6d96a', '#66bd63', '#1a9641']})
    elif index == "water_detection":
        return ("water_detection", {"min": -0.5, "max": 0.8, "palette": ['#f7fbff', '#deebf7', '#9ecae1', '#4292c6', '#2166ac', '#08306b']})
    elif index == "urban_index":
        return ("urban_index", {"min": 0, "max": 1, "palette": ['#ffffff', '#e0e0e0', '#b0b0b0', '#707070', '#252525']})
    elif index == "soil_moisture":
        return ("soil_moisture", {"min": 0, "max": 1, "palette": ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494']})
    elif index == "change_detection":
        # Diverging red-white-blue for change detection
        return ("change_detection", {"min": -1, "max": 1, "palette": ['#b2182b', '#ef8a62', '#f7f7f7', '#67a9cf', '#2166ac']})
    elif index == "ndre":
        return ("ndre", {"min": -1.0, "max": 1.0, "discrete": True, "breaks": [0.0, 0.2, 0.4, 0.6, 0.8], "palette": ['#8c510a', '#d8b365', '#f6e8c3', '#c7eae5', '#5ab4ac', '#01665e']})
    elif index == "lai":
        return ("lai", {"min": 0, "max": 8, "discrete": True, "breaks": [0.5, 2, 6], "palette": ['#ffffe5', '#f7fcb9', '#d9f0a3', '#a1d99b', '#74c476', '#31a354', '#006d2c']})
    elif index == "soil_ph":
        return ("soil_ph", {"min": 0, "max": 2, "discrete": True, "breaks": [0.3, 0.6, 1.0, 1.4], "palette": ['#2c7bb6', '#abd9e9', '#ffffbf', '#fdae61', '#d7191c']})
    else:
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})
