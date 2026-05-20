#!/usr/bin/env python3
"""Pobiera dane BDL dla Puszczy Knyszyńskiej (LP + poza LP),
łączy z opisem taksacyjnym (warstwa mBDL), zapisuje jako TopoJSON.
"""

import json, os, time, urllib.request, urllib.parse
import topojson
from collections import OrderedDict

BBOX = (22.695, 52.90, 23.93, 53.705)  # powiększone o 5km na W i N od oryginału
MAX_RECORDS = 2000
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "pk-data.topojson")

# źródła: (geom_service, taks_service, geom_fields, taks_fields, label)
SOURCES = [
    {
        "geom": "https://mapserver.bdl.lasy.gov.pl/arcgis/rest/services/WMS_BDL_mapa_drzewostanow/MapServer/5/query",
        "taks": "https://mapserver.bdl.lasy.gov.pl/arcgis/rest/services/Mobile/Opis_taksacyjny_mBDL/MapServer/0/query",
        "geom_fields": "adress_forest,species_cd_d,species_age,sub_area,site_type_cd,stand_struct_cd",
        "taks_fields": ("adress_forest,species_cd,species_age,part_cd,storey_species_desc,"
                        "sub_area,site_type_cd,stand_struct_cd,soil_subtype_cd,moisture_name,"
                        "veg_cover_name,prot_category_name,forest_func_name"),
        "label": "LP",
    },
    {
        "geom": "https://mapserver.bdl.lasy.gov.pl/arcgis/rest/services/WMS_BDL_mapa_drzewostanow/MapServer/6/query",
        "taks": "https://mapserver.bdl.lasy.gov.pl/arcgis/rest/services/Mobile/Opis_taksacyjny_lnp_mBDL/MapServer/0/query",
        "geom_fields": "adress_forest,species_cd_d,species_age,sub_area,site_type_cd,stand_struct_cd,owner_cat_name",
        "taks_fields": ("adress_forest,species_cd,species_age,part_cd,storey_species_desc,"
                        "sub_area,site_type_cd,stand_struct_cd,soil_subtype_cd,moisture_name,"
                        "veg_cover_name,prot_category_name,forest_func_name"),
        "label": "lnp",
    },
]


def fetch_all(service, out_fields, with_geom, label):
    all_features = []
    offset = 0
    while True:
        params = {
            "f": "geojson", "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "true" if with_geom else "false",
            "geometry": ",".join(map(str, BBOX)),
            "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": str(offset),
            "resultRecordCount": str(MAX_RECORDS),
        }
        url = f"{service}?{urllib.parse.urlencode(params)}"
        print(f"  [{label}] offset={offset}...")
        req = urllib.request.Request(url, headers={"User-Agent": "python"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        features = data.get("features", [])
        all_features.extend(features)
        print(f"  [{label}] łącznie: {len(all_features)}")
        if len(features) < MAX_RECORDS:
            break
        offset += MAX_RECORDS
        if offset > 80000:
            print(f"  [{label}] przekroczono 80k.")
            break
        time.sleep(0.3)
    return all_features


def parse_species(raw):
    if not raw or not raw.strip():
        return []
    parts = raw.replace("\n", "").split(";")
    result = []
    i = 0
    while i + 9 < len(parts):
        storey_type = parts[i + 2].strip()
        species = parts[i + 3].strip()
        share_raw = parts[i + 4].strip()
        age_raw = parts[i + 5].strip()
        if storey_type == "DRZEW" and species:
            share = share_raw if share_raw else "0"
            age = int(age_raw) if age_raw and age_raw.isdigit() else None
            result.append({"c": species, "a": age, "s": share})
        i += 10
    return result


def merge_source(src):
    label = src["label"]
    print(f"\n--- {label} ---")
    print("Pobieranie geometrii...")
    geom_features = fetch_all(src["geom"], src["geom_fields"], with_geom=True, label=f"{label}-geom")
    print(f"Pobrano {len(geom_features)} geometrii.")

    print("Pobieranie opisu taksacyjnego...")
    taks_features = fetch_all(src["taks"], src["taks_fields"], with_geom=False, label=f"{label}-taks")
    print(f"Pobrano {len(taks_features)} opisów.")

    print("Łączenie...")
    taks_index = {}
    for f in taks_features:
        addr = f["properties"]["adress_forest"].strip()
        taks_index[addr] = f["properties"]

    merged = []
    matched = 0
    for gf in geom_features:
        addr = gf["properties"]["adress_forest"].strip()
        props = gf["properties"].copy()
        geom = gf.get("geometry")

        taks = taks_index.get(addr)
        if taks:
            matched += 1
            for k, v in taks.items():
                if k not in props or props[k] is None:
                    props[k] = v
            raw = (taks.get("storey_species_desc") or "").strip()
        else:
            raw = (props.get("storey_species_desc") or "").strip()

        props["species_list"] = parse_species(raw)

        merged.append({
            "type": "Feature",
            "geometry": geom,
            "properties": OrderedDict(
                (k, props[k]) for k in [
                    "adress_forest", "species_cd", "species_age", "part_cd",
                    "species_list", "owner_cat_name",
                    "sub_area", "site_type_cd", "stand_struct_cd",
                    "soil_subtype_cd", "moisture_name", "veg_cover_name",
                    "prot_category_name", "forest_func_name",
                ] if k in props
            )
        })

    print(f"Dopasowano: {matched}/{len(geom_features)}")
    return merged


def main():
    all_features = []
    for src in SOURCES:
        all_features.extend(merge_source(src))

    print(f"\nŁącznie: {len(all_features)} wydzieleń.")

    fc = {"type": "FeatureCollection", "features": all_features}

    # zapisz tymczasowo GeoJSON
    tmp = OUTPUT.replace(".topojson", ".geojson")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, default=str)
    gj_mb = os.path.getsize(tmp) / 1024 / 1024
    print(f"GeoJSON: {gj_mb:.1f} MB")

    # konwersja do TopoJSON z kwantyzacją
    print("Konwersja do TopoJSON (quantize=1e5)...")
    topo = topojson.Topology(fc, prequantize=True, topology=False)
    topo_obj = topo.to_json()
    if isinstance(topo_obj, str):
        topo_obj = json.loads(topo_obj)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(topo_obj, f, ensure_ascii=False, default=str)

    tj_mb = os.path.getsize(OUTPUT) / 1024 / 1024
    print(f"TopoJSON ({OUTPUT}): {tj_mb:.1f} MB")

    # clean up temp
    os.remove(tmp)


if __name__ == "__main__":
    main()
