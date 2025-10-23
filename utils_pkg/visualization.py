import math

def index_band_and_vis(index, satellite="sentinel2"):
    """Return band name(s) or single-band name and visualization dict for supported indices."""
    if index == "rgb":
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})
    elif index == "ndvi":
        return ("ndvi", {
            "min": -0.2, "max": 0.8,
            "discrete": True,
            "breaks": [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8],
            "palette": [
                '#8B0000', '#E34A33', '#FC8D59', '#FEE08B', '#D9F0A3', '#66C2A5', '#238B45'
            ]
        })
    elif index == "ndwi":
        return ("ndwi", {"min": -0.5, "max": 0.5, "discrete": True, "breaks": [-0.5, -0.1, 0.0, 0.1, 0.3], "palette": ['#8B0000', '#D73027', '#FEE090', '#91BFDB', '#4575B4', '#084594']})
    elif index == "evi":
        return ("evi", {"min": -0.2, "max": 0.6, "palette": ['#67001f', '#b2182b', '#ef8a62', '#fee8c8', '#d9f0a3', '#7fbf7b', '#1a9641']})
    elif index == "savi":
        return ("savi", {"min": -0.2, "max": 0.8, "palette": ['#500000', '#b2182b', '#fddbc7', '#67a9cf', '#2166ac']})
    elif index == "ndmi":
        return ("ndmi", {"min": -0.6, "max": 0.6, "palette": ['#08306b', '#2166ac', '#67a9cf', '#d1e5f0', '#fddbc7', '#b2182b', '#67001f']})
    elif index == "gci":
        return ("gci", {"min": -0.5, "max": 1.5, "palette": ['#ffffe5', '#e5f5e0', '#a1d99b', '#41ab5d', '#006837']})
    elif index == "vegetation_health":
        return ("vegetation_health", {"min": 0, "max": 1, "palette": ['#d73027', '#fc8d59', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850']})
    elif index == "water_detection":
        return ("water_detection", {"min": -0.5, "max": 0.8, "palette": ['#f7fbff', '#deebf7', '#9ecae1', '#3182bd', '#08519c']})
    elif index == "urban_index":
        return ("urban_index", {"min": 0, "max": 1, "palette": ['#f7f7f7', '#cccccc', '#969696', '#636363', '#252525']})
    elif index == "soil_moisture":
        return ("soil_moisture", {"min": 0, "max": 1, "palette": ['#ffffcc', '#c7e9b4', '#7fcdbb', '#41b6c4', '#225ea8']})
    elif index == "change_detection":
        return ("change_detection", {"min": -1, "max": 1, "palette": ['#67001f', '#b2182b', '#ef8a62', '#f7f7f7', '#67a9cf', '#2166ac', '#053061']})
    elif index == "ndre":
        return ("ndre", {"min": -1.0, "max": 1.0, "discrete": True, "breaks": [0.0, 0.2, 0.4, 0.6, 0.8], "palette": ['#8C510A', '#FEE08B', '#ABDDA4', '#66BD63', '#1A9850', '#006837']})
    elif index == "lai":
        return ("lai", {"min": 0, "max": 8, "palette": ['#D1B29A', '#9E7E58', '#B3B3B3', '#B7D7B8', '#A0D97D', '#F2E7A1', '#4C9A2A', '#228B22', '#006400', '#003300', '#004d00', '#004C00'], "breaks": [0.5, 2, 6], "discrete": False})
    elif index == "soil_ph":
        return ("soil_ph", {"min": 0, "max": 2, "discrete": True, "breaks": [0.3, 0.6, 1.0, 1.4], "palette": ['#2c7bb6', '#abd9e9', '#ffffbf', '#fdae61', '#d7191c']})
    else:
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})
