#!/usr/bin/env python3
"""Wczytuje pk-data.topojson, grupuje wydzielenia LP po oddziale,
oblicza unary_union geometrii dla każdego oddziału i zapisuje jako
pk-oddzialy.topojson (tylko dla LP).
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
        x += dx
        y += dy
        coords.append([x * scale[0] + translate[0], y * scale[1] + translate[1]])
    return coords

def dequantize_arc_ref(ref, arcs, scale, translate):
    idx = abs(ref) - 1 if ref < 0 else ref
    arc_data = arcs[idx]
    coords = dequantize_arc(arc_data, scale, translate)
    if ref < 0:
        coords = coords[::-1]
    return coords

def arc_refs_to_polygon_coords(arc_refs, arcs, scale, translate):
    rings = []
    for ring_refs in arc_refs:
        ring_coords = []
        for ref in ring_refs:
            ring_coords.extend(dequantize_arc_ref(ref, arcs, scale, translate))
        rings.append(ring_coords)
    return rings

print("Wczytuję TopoJSON…")
with open(INPUT, "r") as f:
    topo = json.load(f)

scale = topo["transform"]["scale"]
translate = topo["transform"]["translate"]
arcs = topo["arcs"]
geometries = topo["objects"]["data"]["geometries"]

print(f"  {len(geometries)} geometrii, {len(arcs)} łuków")

oddzial_groups = defaultdict(list)
no_oddzial = 0

for g in geometries:
    props = g["properties"]
    owner = props.get("owner_cat_name", "")
    if owner:
        continue
    addr = props.get("adress_forest", "")
    parts = addr.split("-")
    if len(parts) < 4:
        no_oddzial += 1
        continue
    oddzial = parts[3].strip()

    try:
        if g["type"] == "Polygon":
            coords = arc_refs_to_polygon_coords(g["arcs"], arcs, scale, translate)
            poly = shape({"type": "Polygon", "coordinates": coords})
        elif g["type"] == "MultiPolygon":
            polys = []
            for poly_arcs in g["arcs"]:
                coords = arc_refs_to_polygon_coords(poly_arcs, arcs, scale, translate)
                polys.append(coords)
            poly = shape({"type": "MultiPolygon", "coordinates": polys})
        else:
            continue
        oddzial_groups[oddzial].append(poly)
    except Exception as e:
        print(f"  Błąd {addr}: {e}", file=sys.stderr)

print(f"  LP bez oddziału: {no_oddzial}")
print(f"  Grupy oddziałów: {len(oddzial_groups)}")

oddzial_features = []
for oddzial, polys in oddzial_groups.items():
    print(f"  Union oddział {oddzial} ({len(polys)} wydzieleń)…", end=" ", flush=True)
    try:
        merged = unary_union([poly.buffer(1e-8, resolution=1) for poly in polys])
    except Exception as e:
        print(f"retry snap…", file=sys.stderr)
        merged = unary_union([poly.buffer(0.000001, resolution=1) for poly in polys])
    if merged.is_empty:
        print("pusty", file=sys.stderr)
        continue
    if merged.geom_type == "MultiPolygon":
        merged = merged.buffer(1e-8, resolution=1)
    feat = {"type": "Feature", "properties": {"oddzial": oddzial, "count": len(polys)}, "geometry": mapping(merged)}
    oddzial_features.append(feat)
    print(f"✓ ({merged.geom_type})")

fc = {"type": "FeatureCollection", "features": oddzial_features}
oddzial_topo = Topology(fc, prequantize=True, topology=False).to_dict()

with open(OUTPUT, "w") as f:
    json.dump(oddzial_topo, f, ensure_ascii=False)

print(f"Zapisano {len(oddzial_features)} oddziałów do {OUTPUT}")
