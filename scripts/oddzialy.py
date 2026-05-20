#!/usr/bin/env python3
"""Grupy wydzielen: LP po pierwszych 5 czesciach adresu
(Nadl-Obreb-Lesnictwo-Oddzial-Wydzielenie), non-LP po pierwszych 3.
unary_union + srednia wieku wazona powierzchnia (dominant + oldest).
Zapisuje pk-oddzialy.topojson.
"""

import json, sys
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from collections import defaultdict
from topojson import Topology

INPUT = "pk-data.topojson"
OUTPUT = "pk-oddzialy.topojson"

def dequantize_arc(arc, scale, translate):
    coords = []
    x, y = 0, 0
    for dx, dy in arc:
        x += dx; y += dy
        coords.append([x * scale[0] + translate[0], y * scale[1] + translate[1]])
    return coords

def dequantize_arc_ref(ref, arcs, scale, translate):
    idx = abs(ref) - 1 if ref < 0 else ref
    coords = dequantize_arc(arcs[idx], scale, translate)
    return coords[::-1] if ref < 0 else coords

def arc_refs_to_polygon_coords(arc_refs, arcs, scale, translate):
    rings = []
    for ring_refs in arc_refs:
        ring_coords = []
        for ref in ring_refs:
            ring_coords.extend(dequantize_arc_ref(ref, arcs, scale, translate))
        rings.append(ring_coords)
    return rings

def get_dominant_age(p):
    """Wiek gatunku dominujacego (najwiekszy udzial w species_list)."""
    sl = p.get("species_list") or []
    if sl:
        valid = []
        for s in sl:
            try:
                share = int(s.get("s") or 0)
                valid.append((share, s.get("a")))
            except:
                pass
        if valid:
            best = max(valid, key=lambda x: x[0])
            if best[1] is not None:
                try: return float(best[1])
                except: pass
    fallback = p.get("species_age")
    if fallback:
        try: return float(fallback)
        except: pass
    return None

def get_oldest_age(p):
    """Najstarszy wiek z species_list lub species_age."""
    sl = p.get("species_list") or []
    if sl:
        ages = []
        for s in sl:
            if s.get("a") is not None:
                try: ages.append(float(s["a"]))
                except: pass
        if ages: return max(ages)
    return get_dominant_age(p)

print("Wczytuję TopoJSON…")
with open(INPUT, "r") as f:
    topo = json.load(f)

scale = topo["transform"]["scale"]
translate = topo["transform"]["translate"]
arcs = topo["arcs"]
geometries = topo["objects"]["data"]["geometries"]
print(f"  {len(geometries)} geometrii, {len(arcs)} lukow")

groups = defaultdict(list)

for g in geometries:
    p = g["properties"]
    owner = (p.get("owner_cat_name") or "").strip()
    addr = (p.get("adress_forest") or "").strip()
    parts = [x.strip() for x in addr.split("-") if x.strip()]
    if not owner:
        # LP: pierwsze 5 czesci (Nadl-Obreb-Lesnictwo-Oddzial-Wydzielenie)
        if len(parts) >= 5 and parts[0].isdigit():
            key = "-".join(parts[:5])
        else:
            continue
    else:
        # Poza LP: pierwsze 3 czesci (nr dzialki-oddzial-pododdzial)
        if len(parts) >= 3:
            key = "non-LP: " + "-".join(parts[:3])
        else:
            continue
    area = 0
    try: area = float(p.get("sub_area") or 0)
    except: pass

    try:
        if g["type"] == "Polygon":
            coords = arc_refs_to_polygon_coords(g["arcs"], arcs, scale, translate)
            poly = shape({"type": "Polygon", "coordinates": coords})
        elif g["type"] == "MultiPolygon":
            polys = []
            for pa in g["arcs"]:
                coords = arc_refs_to_polygon_coords(pa, arcs, scale, translate)
                polys.append(coords)
            poly = shape({"type": "MultiPolygon", "coordinates": polys})
        else:
            continue
        groups[key].append({
            "poly": poly,
            "area": area,
            "age_dom": get_dominant_age(p),
            "age_old": get_oldest_age(p),
        })
    except Exception as e:
        print(f"  Blad {addr}: {e}", file=sys.stderr)

print(f"  Grupy: {len(groups)}")

features = []
for key, items in groups.items():
    polys = [it["poly"] for it in items]
    # Union
    try:
        merged = unary_union([poly.buffer(1e-8, resolution=1) for poly in polys])
    except:
        merged = unary_union([poly.buffer(0.000001, resolution=1) for poly in polys])
    if merged.is_empty:
        print(f"  {key}: pusty", file=sys.stderr)
        continue
    if merged.geom_type == "MultiPolygon":
        merged = merged.buffer(1e-8, resolution=1)
    # Srednia wieku wazona powierzchnia
    total_area = sum(it["area"] for it in items)
    w_avg_dom = 0
    w_avg_old = 0
    if total_area > 0:
        w_avg_dom = sum((it["age_dom"] or 0) * it["area"] for it in items) / total_area
        w_avg_old = sum((it["age_old"] or 0) * it["area"] for it in items) / total_area
    features.append({
        "type": "Feature",
        "properties": {
            "key": key,
            "count": len(items),
            "avg_age_dominant": round(w_avg_dom, 1),
            "avg_age_oldest": round(w_avg_old, 1),
        },
        "geometry": mapping(merged)
    })
    print(f"  {key}: {len(items)} wydz, avg_dom={w_avg_dom:.0f}, avg_old={w_avg_old:.0f}")

fc = {"type": "FeatureCollection", "features": features}
topo_out = Topology(fc, prequantize=True, topology=False).to_dict()
with open(OUTPUT, "w") as f:
    json.dump(topo_out, f, ensure_ascii=False)
print(f"Zapisano {len(features)} oddzialow do {OUTPUT}")
