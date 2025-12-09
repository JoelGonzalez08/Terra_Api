import math
import json
from pathlib import Path
import ee
from config import BASE_OUTPUT_DIR
import json


def meters_to_degrees(lon, lat, width_m, height_m):
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    half_width_deg = (width_m / 2) / meters_per_deg_lon
    half_height_deg = (height_m / 2) / meters_per_deg_lat
    return [
        lon - half_width_deg, lat - half_height_deg,
        lon + half_width_deg, lat + half_height_deg
    ]


def make_roi_from_geojson(geometry):
    return ee.Geometry(geometry)


def make_roi(lon, lat, width_m, height_m):
    return ee.Geometry.Rectangle(meters_to_degrees(lon, lat, width_m, height_m))


def _parse_coord(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(',', '.')
    try:
        return float(s)
    except Exception:
        raise ValueError(f'Invalid coordinate: {x}')


def center_point_to_bbox(lon, lat, buffer_m=250):
    lat = float(lat)
    lon = float(lon)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    half_h_deg = (buffer_m / 2) / meters_per_deg_lat
    half_w_deg = (buffer_m / 2) / meters_per_deg_lon if meters_per_deg_lon != 0 else (buffer_m / 2) / meters_per_deg_lat
    west = lon - half_w_deg
    east = lon + half_w_deg
    south = lat - half_h_deg
    north = lat + half_h_deg
    return [west, south, east, north]


def get_roi_from_request(req):
    try:
        # 1) kml_id
        if getattr(req, 'kml_id', None):
            kml_id = req.kml_id
            geojson_path = Path(BASE_OUTPUT_DIR) / 'kml_uploads' / f"{kml_id}.geojson"
            if geojson_path.exists():
                with open(geojson_path, 'r', encoding='utf-8') as fh:
                    fc = json.load(fh)
                features = fc.get('features', [])
                if not features:
                    raise ValueError('KML stored but contains no features')
                geom = features[0].get('geometry')
                roi = ee.Geometry(geom)
                try:
                    b = roi.bounds().getInfo()['coordinates'][0]
                    lons = [c[0] for c in b]
                    lats = [c[1] for c in b]
                    roi_bounds = [min(lons), min(lats), max(lons), max(lats)]
                except Exception:
                    # fallback compute from coords
                    try:
                        geom_coords = geom.get('coordinates')
                        if geom.get('type') == 'Polygon':
                            coords = geom_coords[0]
                        elif geom.get('type') == 'MultiPolygon':
                            coords = [pt for poly in geom_coords for pt in poly[0]]
                        else:
                            coords = []
                        if coords:
                            lons = [c[0] for c in coords]
                            lats = [c[1] for c in coords]
                            roi_bounds = [min(lons), min(lats), max(lons), max(lats)]
                        else:
                            roi_bounds = None
                    except Exception:
                        roi_bounds = None
                return roi, roi_bounds

        # 2) geometry
        if getattr(req, 'geometry', None):
            geom = req.geometry
            roi = ee.Geometry(geom)
            try:
                b = roi.bounds().getInfo()['coordinates'][0]
                lons = [c[0] for c in b]
                lats = [c[1] for c in b]
                roi_bounds = [min(lons), min(lats), max(lons), max(lats)]
            except Exception:
                try:
                    geom_coords = geom.get('coordinates')
                    if geom.get('type') == 'Polygon':
                        coords = geom_coords[0]
                    elif geom.get('type') == 'MultiPolygon':
                        coords = [pt for poly in geom_coords for pt in poly[0]]
                    else:
                        coords = []
                    if coords:
                        lons = [c[0] for c in coords]
                        lats = [c[1] for c in coords]
                        roi_bounds = [min(lons), min(lats), max(lons), max(lats)]
                    else:
                        roi_bounds = None
                except Exception:
                    roi_bounds = None
            return roi, roi_bounds

        # 3) lon/lat center
        if getattr(req, 'lon', None) is not None and getattr(req, 'lat', None) is not None:
            try:
                lon = _parse_coord(getattr(req, 'lon'))
                lat = _parse_coord(getattr(req, 'lat'))
            except Exception:
                raise ValueError('Invalid lon/lat')
            buffer_m = getattr(req, 'buffer_m', None) or getattr(req, 'radius_m', None) or 250
            try:
                buffer_m = float(buffer_m)
            except Exception:
                buffer_m = 250.0
            bbox = center_point_to_bbox(lon, lat, buffer_m=buffer_m)
            roi = ee.Geometry.Rectangle(bbox)
            roi_bounds = bbox
            return roi, roi_bounds

        # 4) lon/lat + width/height
        if getattr(req, 'lon', None) is not None and getattr(req, 'lat', None) is not None and getattr(req, 'width_m', None) and getattr(req, 'height_m', None):
            lon = _parse_coord(getattr(req, 'lon'))
            lat = _parse_coord(getattr(req, 'lat'))
            width_m = float(getattr(req, 'width_m'))
            height_m = float(getattr(req, 'height_m'))
            rect = meters_to_degrees(lon, lat, width_m, height_m)
            roi = ee.Geometry.Rectangle(rect)
            roi_bounds = rect
            return roi, roi_bounds

        raise ValueError('No ROI provided (kml_id, geometry, or lon/lat needed)')
    except Exception:
        raise


def split_feature_collection(fc: dict):
    """Divide un GeoJSON FeatureCollection en una lista de features con metadatos útiles.

    Retorna lista de dicts: { 'id': str, 'name': Optional[str], 'geometry': dict, 'properties': dict, 'area_m2': Optional[float] }
    Intenta calcular el area en metros cuadrados usando Earth Engine; si falla, deja area_m2 en None.
    """
    out = []
    if not fc:
        return out
    features = fc.get('features') if isinstance(fc, dict) else None
    if not features:
        return out
    for i, feat in enumerate(features):
        try:
            feat_id = feat.get('id') or feat.get('properties', {}).get('id') or feat.get('properties', {}).get('name') or f'feature_{i+1}'
            props = feat.get('properties', {}) or {}
            name = props.get('name') or props.get('title') or None
            geom = feat.get('geometry')
            area_m2 = None
            if geom:
                try:
                    g = ee.Geometry(geom)
                    # usar area() geodesic
                    area_m2 = float(g.area().getInfo())
                except Exception:
                    # fallback: intentar calcular area por bounds aproximado
                    try:
                        coords = None
                        if geom.get('type') == 'Polygon':
                            coords = geom.get('coordinates', [[]])[0]
                        elif geom.get('type') == 'MultiPolygon':
                            coords = [pt for poly in geom.get('coordinates', []) for pt in poly[0]]
                        if coords:
                            lons = [c[0] for c in coords]
                            lats = [c[1] for c in coords]
                            width_deg = max(lons) - min(lons)
                            height_deg = max(lats) - min(lats)
                            # aproximación: 1 deg lat ~ 111.32 km, lon depends on lat
                            avg_lat = sum(lats) / len(lats) if lats else 0
                            meters_per_deg_lat = 111320.0
                            meters_per_deg_lon = 111320.0 * math.cos(math.radians(avg_lat)) if avg_lat else 111320.0
                            approx_m2 = (width_deg * meters_per_deg_lon) * (height_deg * meters_per_deg_lat)
                            area_m2 = float(abs(approx_m2))
                    except Exception:
                        area_m2 = None
            out.append({'id': str(feat_id), 'name': name, 'geometry': geom, 'properties': props, 'area_m2': area_m2})
        except Exception:
            # skip malformed feature but keep iteration
            continue
    return out
