from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user_optional
from schemas.models import ComputeRequest, ComputeResponse
from services.ee.ee_client import compute_sentinel2_index, get_sentinel2_time_series
from config import BASE_OUTPUT_DIR
from utils_pkg import ensure_outputs_dir, timestamped_base
import ee
from pathlib import Path
import requests
import time
from services.db import insert_asset, insert_measurement
import traceback
import os

ERROR_LOG_DIR = Path(BASE_OUTPUT_DIR) / 'compute_errors'
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()


@router.post('/compute', response_model=ComputeResponse)
def compute(req: ComputeRequest, current_user: dict = Depends(get_current_user_optional)):
    # Manejo explícito de errores: re-lanzar HTTPException para que FastAPI devuelva el código correcto
    try:
        # ROI selection logic (kml_id, geometry, lon/lat)
        from utils_pkg import get_roi_from_request
        roi, roi_bounds = get_roi_from_request(req)

        band, vis = None, None
        # Determine band/vis
        from utils_pkg import index_band_and_vis
        band, vis = index_band_and_vis(req.index, satellite='sentinel2')

        if req.mode == 'heatmap':
            img = compute_sentinel2_index(roi, req.start, req.end, req.index, getattr(req, 'cloud_pct', 30))
            if img is None:
                print(f"compute: compute_sentinel2_index returned None for index={req.index}")
                raise HTTPException(status_code=404, detail='No images')
            # Try to inspect the image bands for debugging
            try:
                band_names = img.bandNames().getInfo()
                print(f"compute: compute_sentinel2_index returned image with bands={band_names}")
            except Exception as e:
                print(f"compute: could not read bandNames from image: {e}")
                band_names = None

            try:
                layer = img.select(band)
            except Exception as e:
                # Log detailed info and re-raise as 500 so caller sees the failure
                import traceback
                tb = traceback.format_exc()
                print(f"compute: failed to select band '{band}' from image: {e}\n{tb}")
                raise HTTPException(status_code=500, detail=f"Error selecting band '{band}': {e}")

            # Prepare visualization parameters. If the vis requests a discrete (classified) palette,
            # build a classified image and create a vis_map that maps classes 0..N to the palette.
            vis_map = None
            # If vis is a dict, copy it (we'll override for discrete)
            try:
                vis_map = dict(vis) if isinstance(vis, dict) else None
            except Exception:
                vis_map = None

            # If the vis requests a discrete (classified) palette, build a classified image
            try:
                if isinstance(vis, dict) and vis.get('discrete'):
                    breaks = vis.get('breaks') or []
                    if breaks:
                        # Build an expression that assigns class indexes based on breaks
                        expr = None
                        # Using ee.Image.gt/lt to create masks per interval
                        base = layer
                        classes = []
                        # below first break
                        prev = None
                        for i, b in enumerate(breaks):
                            if prev is None:
                                mask = base.lte(float(b))
                            else:
                                mask = base.gt(float(prev)).And(base.lte(float(b)))
                            classes.append(mask.multiply(i))
                            prev = b
                        # above last break
                        classes.append(base.gt(float(prev)).multiply(len(breaks)))
                        classified = ee.Image(classes[0])
                        for c in classes[1:]:
                            classified = classified.add(c)
                        # Replace layer with a single-band classified image for visualization
                        layer = classified.rename('class')
                        # Build vis_map for classes 0..n
                        num_classes = len(breaks) + 1
                        palette = list(vis.get('palette') or [])
                        # Ensure palette length equals num_classes; pad by repeating last color if needed
                        if len(palette) < num_classes:
                            if palette:
                                while len(palette) < num_classes:
                                    palette.append(palette[-1])
                            else:
                                palette = ['#000000'] * num_classes
                        elif len(palette) > num_classes:
                            palette = palette[:num_classes]
                        # classes are 0..num_classes-1
                        vis_map = {'min': 0, 'max': num_classes - 1, 'palette': palette}
            except Exception as e:
                print('compute: failed building discrete classified image', e)

            # Calcular estadísticas sobre el ROI: mean, min, max, stddev
            min_val = max_val = mean_val = stddev_val = None
            try:
                # Determinar banda objetivo (si layer tiene varias, tomar la primera)
                band_names = layer.bandNames().getInfo()
                target_band = band_names[0] if band_names else None
                if target_band:
                    reducer = ee.Reducer.mean().combine(ee.Reducer.min(), None, True).combine(ee.Reducer.max(), None, True).combine(ee.Reducer.stdDev(), None, True)
                    rr = layer.select([target_band]).reduceRegion(reducer, geometry=roi, scale=10, maxPixels=1e9, bestEffort=True)
                    stats_info = rr.getInfo()
                    # Guardar el objeto raw de estadísticas para depuración
                    try:
                        from utils_pkg import save_compute_stats
                        stats_file = save_compute_stats(stats_info, base if 'base' in locals() else None)
                    except Exception:
                        stats_file = None
                    # keys could be like '<band>_mean' or 'mean' depending on EE; comprobar varias
                    mean_val = stats_info.get(f"{target_band}_mean") if isinstance(stats_info, dict) else None
                    if mean_val is None:
                        mean_val = stats_info.get('mean') or stats_info.get(target_band)
                    min_val = stats_info.get(f"{target_band}_min") if isinstance(stats_info, dict) else None
                    if min_val is None:
                        min_val = stats_info.get('min')
                    max_val = stats_info.get(f"{target_band}_max") if isinstance(stats_info, dict) else None
                    if max_val is None:
                        max_val = stats_info.get('max')
                    stddev_val = stats_info.get(f"{target_band}_stdDev") if isinstance(stats_info, dict) else None
                    if stddev_val is None:
                        stddev_val = stats_info.get('stdDev')
                    # Coerce to floats when possible
                    try:
                        mean_val = float(mean_val) if mean_val is not None else None
                    except Exception:
                        mean_val = None
                    try:
                        min_val = float(min_val) if min_val is not None else None
                    except Exception:
                        min_val = None
                    try:
                        max_val = float(max_val) if max_val is not None else None
                    except Exception:
                        max_val = None
                    try:
                        stddev_val = float(stddev_val) if stddev_val is not None else None
                    except Exception:
                        stddev_val = None
            except Exception:
                min_val = max_val = mean_val = stddev_val = None

            # Build a visualization image so tiles are already colored on server side.
            try:
                # If vis_map has a palette and the layer is single-band (not RGB), use visualize()
                is_rgb_band = isinstance(band, (list, tuple))
            except Exception:
                is_rgb_band = False

            vis_image = layer
            visualized_on_server = False
            # Prefer palette from vis_map (created for discrete), otherwise from vis
            palette_to_use = None
            palette_min = None
            palette_max = None
            try:
                if isinstance(vis_map, dict) and vis_map.get('palette'):
                    palette_to_use = list(vis_map.get('palette'))
                    palette_min = vis_map.get('min')
                    palette_max = vis_map.get('max')
                elif isinstance(vis, dict) and vis.get('palette'):
                    palette_to_use = list(vis.get('palette'))
                    palette_min = vis.get('min')
                    palette_max = vis.get('max')
                # Fallback: if palette missing, but min/max present, we can still call getMapId with those
            except Exception:
                palette_to_use = None

            # If single-band and we have a palette, try to bake colors server-side using visualize()
            try:
                if palette_to_use and (not is_rgb_band):
                    # Ensure palette entries are strings and non-empty
                    palette_to_use = [str(p) for p in palette_to_use if p]
                    if not palette_to_use:
                        palette_to_use = ['#000000', '#ffffff']
                    # Ensure min/max defaults
                    if palette_min is None:
                        palette_min = 0
                    if palette_max is None:
                        palette_max = 1
                    try:
                        vis_image = layer.visualize(min=palette_min, max=palette_max, palette=palette_to_use)
                        # Ensure the visualized image is an 8-bit RGB image
                        try:
                            vis_image = vis_image.toUint8()
                        except Exception:
                            pass
                        visualized_on_server = True
                        print('compute: successfully visualized image on server')
                    except Exception as e:
                        # visualize() may fail for classified images depending on types; fallback to raw layer
                        print('compute: visualize() failed, will rely on getMapId with vis params', e)
                        vis_image = layer
                else:
                    # No palette or RGB bands: keep the raw layer and rely on getMapId with vis_map/vis
                    vis_image = layer
            except Exception as e:
                print('compute: error while preparing vis_image', e)
                vis_image = layer
            # Debug: log visualization decision & maps
            try:
                print(f"compute: vis_map={vis_map}, visualized_on_server={visualized_on_server}")
                try:
                    bn = vis_image.bandNames().getInfo()
                    print(f"compute: vis_image bandNames={bn}")
                except Exception:
                    print("compute: could not get bandNames for vis_image")
            except Exception:
                pass
            try:
                # Try to log a small sample value to confirm image contains color bands
                try:
                    sample = vis_image.reduceRegion(ee.Reducer.first(), geometry=roi, scale=10, maxPixels=1e9).getInfo()
                    print(f"compute: vis_image sample values={sample}")
                except Exception:
                    pass
            except Exception:
                pass

            # If export requested
            if getattr(req, 'export_format', None) in ('png', 'geotiff'):
                ensure_outputs_dir()
                base, ts = timestamped_base(req.index, req.start, req.end)
                saved = {}
                if req.export_format == 'geotiff':
                    geotiff_path = Path(BASE_OUTPUT_DIR) / f"{base}.tif"
                    url = layer.getDownloadURL({'scale': 10, 'region': roi, 'format': 'GEO_TIFF', 'crs': 'EPSG:4326'})
                    r = requests.get(url, stream=True)
                    r.raise_for_status()
                    with open(geotiff_path, 'wb') as fh:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                fh.write(chunk)
                    saved['geotiff'] = str(geotiff_path)
                    # insert asset
                    try:
                        bbox = roi.bounds().getInfo() if hasattr(roi, 'bounds') else None
                    except Exception:
                        bbox = None
                    try:
                        footprint = roi.getInfo()
                    except Exception:
                        footprint = None
                    insert_asset(asset_id=base + '.tif', product=req.index, sensor='sentinel-2', url_s3=str(geotiff_path), epsg=4326, resolution_m=10, acquired_ts=None, ingested_ts=time.strftime('%Y-%m-%dT%H:%M:%SZ'), footprint=footprint, bbox=bbox, min_val=min_val, max_val=max_val, mean_val=mean_val, stddev_val=stddev_val, cog_ok=True, tenant_id=None, plot_id=(req.kml_id if getattr(req, 'kml_id', None) else None))
                elif req.export_format == 'png':
                    png_path = Path(BASE_OUTPUT_DIR) / f"{base}.png"
                    try:
                        thumb_params = dict(vis_map) if vis_map else {}
                    except Exception:
                        thumb_params = vis_map if vis_map else {}
                    thumb_params.update({'region': roi, 'dimensions': 1024})
                    try:
                        # Use vis_image which may already be visualized
                        url = vis_image.getThumbURL(thumb_params)
                    except Exception:
                        url = vis_image.getDownloadURL({'scale': 10, 'region': roi, 'format': 'PNG'})
                    r = requests.get(url, stream=True)
                    r.raise_for_status()
                    with open(png_path, 'wb') as fh:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                fh.write(chunk)
                    saved['png'] = str(png_path)
                    try:
                        bbox = roi.bounds().getInfo() if hasattr(roi, 'bounds') else None
                    except Exception:
                        bbox = None
                    try:
                        footprint = roi.getInfo()
                    except Exception:
                        footprint = None
                    insert_asset(asset_id=base + '.png', product=req.index, sensor='sentinel-2', url_s3=str(png_path), epsg=4326, resolution_m=10, acquired_ts=None, ingested_ts=time.strftime('%Y-%m-%dT%H:%M:%SZ'), footprint=footprint, bbox=bbox, min_val=min_val, max_val=max_val, mean_val=mean_val, stddev_val=stddev_val, cog_ok=True, tenant_id=None, plot_id=(req.kml_id if getattr(req, 'kml_id', None) else None))

                # Antes de devolver, redondear las estadísticas a dos cifras significativas
                try:
                    from utils_pkg import round_sig
                    min_r = round_sig(min_val, sig=2)
                    max_r = round_sig(max_val, sig=2)
                    mean_r = round_sig(mean_val, sig=2)
                    std_r = round_sig(stddev_val, sig=2)
                except Exception:
                    min_r, max_r, mean_r, std_r = min_val, max_val, mean_val, stddev_val
                return {'mode': req.mode, 'index': req.index, 'roi': roi.getInfo(), 'roi_bounds': roi_bounds, 'saved_files': saved, 'min_val': min_r, 'max_val': max_r, 'mean_val': mean_r, 'stddev_val': std_r, 'stats_file': stats_file if 'stats_file' in locals() else None}

            # Otherwise return tiles and insert metadata for tiles
            # For visualized RGB images, pass an empty vis dict to getMapId because colors are baked in.
            try:
                # If we already visualized on server, call getMapId with empty params (image is RGB)
                if visualized_on_server:
                    print("compute: image was visualized on server; calling getMapId with empty params")
                    m = vis_image.getMapId({})
                else:
                    # We did not visualize; if we detected a palette earlier, pass it to getMapId so EE colors tiles
                    if 'palette_to_use' in locals() and palette_to_use and (not is_rgb_band):
                        gm = {'min': (palette_min if palette_min is not None else 0), 'max': (palette_max if palette_max is not None else 1), 'palette': palette_to_use}
                        print(f"compute: calling getMapId with palette params={gm}")
                        m = vis_image.getMapId(gm)
                    else:
                        getmap_params = vis_map if vis_map else (vis if isinstance(vis, dict) else {})
                        print(f"compute: calling getMapId with params={getmap_params}")
                        m = vis_image.getMapId(getmap_params)
            except Exception as e:
                print('compute: getMapId failed', e)
                raise HTTPException(status_code=500, detail=f'Error generating tiles: {e}')
            # Extract tile URL robustly and log the getMapId response on unexpected shapes
            try:
                tile_url = m['tile_fetcher'].url_format
            except Exception as e:
                try:
                    # If m is a dict-like with different keys, print full repr for debugging
                    print(f"compute: unexpected getMapId response: {repr(m)}")
                except Exception:
                    print("compute: unexpected getMapId response and failed to repr(m)")
                raise HTTPException(status_code=500, detail=f"Error generating tiles: unexpected getMapId response ({e})")
            try:
                bbox = roi.bounds().getInfo() if hasattr(roi, 'bounds') else None
            except Exception:
                bbox = None
            try:
                footprint = roi.getInfo()
            except Exception:
                footprint = None
            insert_asset(asset_id=f"{req.index}_{int(time.time())}_tiles", product=req.index, sensor='sentinel-2', url_s3=tile_url, epsg=4326, resolution_m=10, acquired_ts=None, ingested_ts=time.strftime('%Y-%m-%dT%H:%M:%SZ'), footprint=footprint, bbox=bbox, min_val=min_val, max_val=max_val, mean_val=mean_val, stddev_val=stddev_val, cog_ok=False, tenant_id=None, plot_id=(req.kml_id if getattr(req, 'kml_id', None) else None))
            # Prepare vis metadata for response. If we baked colors on server, indicate that and include palette for legend.
            if visualized_on_server:
                vis_return = {'baked': True, 'palette': vis_map.get('palette') if isinstance(vis_map, dict) else None, 'min': vis_map.get('min') if isinstance(vis_map, dict) else None, 'max': vis_map.get('max') if isinstance(vis_map, dict) else None}
            else:
                vis_return = vis if isinstance(vis, dict) else vis_map

            return {'mode': req.mode, 'index': req.index, 'roi': roi.getInfo(), 'roi_bounds': roi_bounds, 'tileUrlTemplate': tile_url, 'vis': vis_return, 'min_val': min_val, 'max_val': max_val, 'mean_val': mean_val, 'stddev_val': stddev_val, 'stats_file': stats_file if 'stats_file' in locals() else None}

        elif req.mode == 'series':
            # Obtener serie temporal optimizada desde ee_client
            try:
                series = get_sentinel2_time_series(roi, req.start, req.end, req.index, getattr(req, 'cloud_pct', 70))
            except HTTPException:
                # Re-lanzar HTTPException tal cual
                raise
            except Exception as e:
                # Falla al obtener la serie desde EE
                raise HTTPException(status_code=500, detail=f'Error obteniendo series temporales: {e}')

            # Convertir puntos a formato esperado por ComputeResponse.series
            pts = []
            for p in series:
                try:
                    date = p.get('date') or p.get('datetime')
                    value = None
                    # Priorizar mean si existe
                    if 'mean' in p and p['mean'] is not None:
                        # ya redondeado en get_sentinel2_time_series, pero asegurar float
                        try:
                            value = float(p['mean'])
                        except Exception:
                            value = None
                    elif 'value' in p and p['value'] is not None:
                        value = float(p['value'])
                    pts.append({'date': date, 'value': value})
                except Exception:
                    continue

            saved = {}
            # Si se pide export csv, escribir CSV con la serie temporal
            if getattr(req, 'export_format', None) == 'csv':
                ensure_outputs_dir()
                base, ts = timestamped_base(req.index, req.start, req.end)
                csv_path = Path(BASE_OUTPUT_DIR) / f"{base}.csv"
                try:
                    import csv
                    with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                        writer = csv.writer(fh)
                        writer.writerow(['date', 'value'])
                        for pt in pts:
                            writer.writerow([pt.get('date'), pt.get('value')])
                    saved['csv'] = str(csv_path)
                except Exception as e:
                    # No bloquear si falla guardar CSV
                    saved['csv_error'] = str(e)

                # Además opcionalmente generar un PNG de la mediana para referencia visual
                try:
                    img = compute_sentinel2_index(roi, req.start, req.end, req.index, getattr(req, 'cloud_pct', 70))
                    if img is not None:
                        layer = img.select(band)
                        png_path = Path(BASE_OUTPUT_DIR) / f"{base}_series.png"
                        try:
                            try:
                                thumb_params = dict(vis_map) if vis_map else {}
                            except Exception:
                                thumb_params = vis_map if vis_map else {}
                            thumb_params.update({'region': roi, 'dimensions': 1024})
                            try:
                                url = vis_image.getThumbURL(thumb_params)
                            except Exception:
                                url = vis_image.getDownloadURL({'scale': 10, 'region': roi, 'format': 'PNG'})
                            r = requests.get(url, stream=True)
                            r.raise_for_status()
                            with open(png_path, 'wb') as fh:
                                for chunk in r.iter_content(chunk_size=8192):
                                    if chunk:
                                        fh.write(chunk)
                            saved['png'] = str(png_path)
                        except Exception:
                            # don't block series result if thumbnail fails
                            pass
                except Exception:
                    pass

            # Guardar cada punto de la serie en la tabla measurement (fecha de pasada)
            try:
                for pt in pts:
                    try:
                        if not pt.get('date'):
                            continue
                        insert_measurement(metric_id=None, tenant_id=None, plot_id=(req.kml_id if getattr(req, 'kml_id', None) else None), ts=pt.get('date'), metric_type=req.index, value=pt.get('value'), quality=None)
                    except Exception:
                        continue
            except Exception:
                # No bloquear por fallos en inserción de medidas
                pass

            # Insertar metadata básica en la DB (serie generada)
            try:
                try:
                    bbox = roi.bounds().getInfo() if hasattr(roi, 'bounds') else None
                except Exception:
                    bbox = None
                try:
                    footprint = roi.getInfo()
                except Exception:
                    footprint = None
                insert_asset(asset_id=f"{req.index}_{int(time.time())}_series", product=req.index, sensor='sentinel-2', url_s3=(saved.get('csv') if saved else None), epsg=4326, resolution_m=10, acquired_ts=None, ingested_ts=time.strftime('%Y-%m-%dT%H:%M:%SZ'), footprint=footprint, bbox=bbox, cog_ok=False, tenant_id=None, plot_id=(req.kml_id if getattr(req, 'kml_id', None) else None))
            except Exception:
                # No bloquear la respuesta si falla el insert en la DB
                pass

            return {'mode': req.mode, 'index': req.index, 'roi': roi.getInfo(), 'roi_bounds': roi_bounds, 'series': pts, 'saved_files': saved}

        else:
            raise HTTPException(status_code=400, detail='mode inválido')
    except HTTPException:
        # Re-lanzar errores HTTP para que FastAPI maneje códigos correctamente
        raise
    except Exception as ex:
        # Loggear traceback completo en archivo para depuración local
        try:
            import datetime
            ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            log_path = ERROR_LOG_DIR / f'compute_error_{ts}.log'
            with open(log_path, 'w', encoding='utf-8') as fh:
                fh.write('Exception: ' + str(ex) + '\n\n')
                fh.write('Traceback:\n')
                traceback.print_exc(file=fh)
        except Exception:
            log_path = None
        # Devolver mensaje que indique al usuario dónde mirar el log
        msg = 'Error interno en /compute'
        if log_path:
            msg += f', ver registro en: {str(log_path)}'
        raise HTTPException(status_code=500, detail=msg)
