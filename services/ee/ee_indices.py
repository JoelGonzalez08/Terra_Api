import ee


def compute_sentinel2_index(roi, start, end, index, cloud_pct=30):
    """Compute various Sentinel-2 based indices for heatmaps.

    Returns an ee.Image clipped to the roi, with a single band named after the index.
    """
    from services.ee.ee_client import get_sentinel2_collection

    collection = get_sentinel2_collection(roi, start, end, cloud_pct)

    # If no images, return None
    try:
        size = int(collection.size().getInfo())
    except Exception:
        size = 0
    print(f"Sentinel-2 Heatmap: Found {size} images for composition (cloud_pct<{cloud_pct})")
    if size == 0:
        return None

    # Build a robust median composite; fallback to first() if median fails
    try:
        composite = collection.median().clip(roi)
    except Exception:
        try:
            composite = collection.first().clip(roi)
        except Exception:
            return None

    idx = (index or '').lower()

    # RGB (true color)
    if idx == 'rgb':
        try:
            return composite.select(['B4', 'B3', 'B2'])
        except Exception:
            return composite

    # NDVI
    if idx == 'ndvi':
        ndvi = composite.normalizedDifference(['B8', 'B4']).rename('ndvi')
        return ndvi.clip(roi)

    # NDWI (water)
    if idx == 'ndwi':
        ndwi = composite.normalizedDifference(['B3', 'B8']).rename('ndwi')
        return ndwi.clip(roi)

    # NDMI (moisture)
    if idx == 'ndmi':
        ndmi = composite.normalizedDifference(['B8', 'B11']).rename('ndmi')
        try:
            ndmi = ndmi.clamp(-0.6, 0.6)
        except Exception:
            pass
        return ndmi.clip(roi)

    # NDRE (red edge)
    if idx == 'ndre':
        try:
            ndre = composite.normalizedDifference(['B8', 'B5']).rename('ndre')
        except Exception:
            ndre = composite.normalizedDifference(['B8', 'B4']).rename('ndre')
        try:
            ndre = ndre.clamp(-0.5, 0.6)
        except Exception:
            pass
        return ndre.clip(roi)

    # EVI
    if idx == 'evi':
        evi = composite.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {
                'NIR': composite.select('B8'),
                'RED': composite.select('B4'),
                'BLUE': composite.select('B2')
            }
        ).rename('evi')
        try:
            evi = evi.clamp(-0.2, 0.6)
        except Exception:
            pass
        return evi.clip(roi)

    # SAVI (soil-adjusted vegetation index)
    if idx == 'savi':
        savi = composite.expression(
            '(1.5) * ((NIR - RED) / (NIR + RED + 0.5))',
            {
                'NIR': composite.select('B8'),
                'RED': composite.select('B4')
            }
        ).rename('savi')
        try:
            savi = savi.clamp(-0.5, 1.0)
        except Exception:
            pass
        return savi.clip(roi)

    # LAI: empirical from NDVI
    if idx == 'lai':
        ndvi = composite.normalizedDifference(['B8', 'B4'])
        lai = ndvi.multiply(3.618).subtract(0.118)
        try:
            # Ensure non-negative LAI values
            lai = lai.max(0)
        except Exception:
            pass
        lai = lai.rename('lai')
        try:
            print('compute_sentinel2_index: returning LAI image')
        except Exception:
            pass
        return lai.clip(roi)

    # soil_ph: proxy using SWIR/NIR ratio
    if idx == 'soil_ph':
        try:
            ratio = composite.select('B11').divide(composite.select('B8')).rename('soil_ph_raw')
            soil_ph = ratio.multiply(1.0).rename('soil_ph')
            return soil_ph.clip(roi)
        except Exception:
            ndvi = composite.normalizedDifference(['B8', 'B4']).rename('soil_ph')
            return ndvi.clip(roi)

    # Default fallback: normalizedDifference(NIR, RED)
    try:
        fallback = composite.normalizedDifference(['B8', 'B4']).rename(idx)
        return fallback.clip(roi)
    except Exception:
        return composite
