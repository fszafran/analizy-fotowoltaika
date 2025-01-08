import arcpy
import re
from typing import List
import os
import time

class Category:
    def __init__(self, name):
        self.name = name
        self.feature_list = []
    
    def add_feature_class(self, featureClass):
        self.feature_list.append(featureClass)

def create_categories(featureClasses: List[str]) -> List[Category]:
    siecWodna = Category("SiecWodna")
    siecDrogowa = Category("SiecDrogowa")
    lasy = Category("Lasy")
    budynki = Category("Budynki")
    siecEnergetyczna = Category("SiecEnergetyczna")

    for fc in featureClasses:
        if re.search(r"SWRS", fc):
            polygonised_layer = arcpy.analysis.Buffer(fc, f"{fc}_polygon", "1 Meter")
            siecWodna.add_feature_class(polygonised_layer)
            arcpy.management.Delete(fc)
        elif re.search(r"PTWP", fc):
            siecWodna.add_feature_class(fc)
        elif re.search(r"SKJZ", fc):
            siecDrogowa.add_feature_class(fc)
        elif re.search(r"BUBD", fc):
            budynki.add_feature_class(fc)
        elif re.search(r"PTLZ", fc):
            lasy.add_feature_class(fc)
        elif re.search(r"SULN", fc):
            siecEnergetyczna.add_feature_class(fc)
    return [siecWodna, siecDrogowa, lasy, budynki, siecEnergetyczna]

def clip_categories_to_area(categories: List[Category], area: str) -> None:
    for cat in categories:
        if cat.feature_list: 
            mergeOutput = f"merged_{cat.name}"
            clipOutput = f"clipped_{cat.name}"
            merged = arcpy.management.Merge(cat.feature_list, mergeOutput)
            arcpy.analysis.Clip(merged, area, clipOutput)

def get_euclidean_distances() -> List[str]:
    clippedCategories = arcpy.ListFeatureClasses("clipped*")
    for layer in clippedCategories:
        if re.search(r"clipped_SiecDrogowa", layer):
            continue
        if re.search(r"clipped_Budynki", layer):
            arcpy.analysis.Select(layer, "Budynki_miesz", "FOBUD = 'budynki mieszkalne'")
            dist = arcpy.sa.EucDistance("Budynki_miesz", cell_size=5)
            dist.save(f"EuCDist_{layer}")
            continue
        dist = arcpy.sa.EucDistance(layer, cell_size=5)
        dist.save(f"EuCDist_{layer}")


def merge_NMTs(rasterFolderDirectory: str) -> None:
    rasters = []
    coordinateSystem = arcpy.SpatialReference(2180)
    for file in os.listdir(rasterFolderDirectory):
        if file.endswith(".asc"):
            raster = arcpy.Raster(os.path.join(rasterFolderDirectory, file))
            rasters.append(raster)    
    arcpy.management.MosaicToNewRaster(
        rasters, rasterFolderDirectory, "merged_raster.tif",
        coordinate_system_for_the_raster=coordinateSystem, number_of_bands=1,
        mosaic_method="LAST", pixel_type="32_BIT_FLOAT", cellsize="5"
    )

def clip_merged_raster_to_area(mergedRaster: str, area: str) -> None:
    clipped = arcpy.sa.ExtractByMask(
        in_raster=mergedRaster,
        in_mask_data=area,
        extraction_area="INSIDE",
        analysis_extent="#"
    )
    clipped.save("clipped_NMT")
    
def get_layers_from_directories(directories: List[str], environment: str) -> None:
    print("Getting layers from directories")
    patterns = ["OT_SWRS_L", "OT_BUBD_A", "OT_SKJZ_L", "OT_PTWP_A", "OT_PTLZ_A", "OT_SULN_L"]
    paths = prepare_filenames(directories)
    for path in paths:
        if any(pattern in path for pattern in patterns) and path.endswith(".shp"):
            arcpy.conversion.FeatureClassToGeodatabase(path, environment)

def prepare_filenames(directories: List[str]) -> List[str]:
    patterns = ["OT_SWRS_L", "OT_BUBD_A", "OT_SKJZ_L", "OT_PT", "OT_SULN_L"]
    paths = []
    for directory in directories:
        for file in os.listdir(directory):
            if any(pattern in file for pattern in patterns):
                sanitizedPath = sanitize_path(directory, os.path.join(directory, file))
                if sanitizedPath:
                    paths.append(sanitizedPath)
    return paths   

def sanitize_path(directory: str, path: str) -> str:
    parts = path.split("10k.")
    if len(parts) > 1:
        newPath = os.path.join(directory, parts[1])
        os.rename(path, newPath)
        return newPath
    return path

def woda_criterium() -> None:
    distWoda = "EuCDist_clipped_SiecWodna"
    max_val = arcpy.management.GetRasterProperties(distWoda, "MAXIMUM").getOutput(0)
    strong = arcpy.sa.FuzzyMembership(distWoda, arcpy.sa.FuzzyLinear(0, 100))
    strong = arcpy.sa.Reclassify(strong, "Value", arcpy.sa.RemapRange([[0, 0.999, 0]]))
    strong.save("strong_woda")
    fuzzy = arcpy.sa.FuzzyMembership(distWoda, arcpy.sa.FuzzyLinear(max_val, 102))
    final = arcpy.sa.FuzzyOverlay([strong, fuzzy], "AND")
    final.save("fuzzy_siec_wodna")

def drogi_criterium() -> None:
    drogi = "clipped_SiecDrogowa"
    density = arcpy.sa.LineDensity(drogi, None, cell_size=5, area_unit_scale_factor="SQUARE_KILOMETERS")
    maxVal = arcpy.management.GetRasterProperties(density, "MAXIMUM").getOutput(0)
    fuzz = arcpy.sa.FuzzyMembership(density, arcpy.sa.FuzzyLinear(0, maxVal))
    fuzz.save("fuzzy_siec_drogowa")

def lasy_criterium() -> None:
    distLasy = "EuCDist_clipped_Lasy"
    strong = arcpy.sa.FuzzyMembership(distLasy, arcpy.sa.FuzzyLinear(0, 15))
    strong = arcpy.sa.Reclassify(strong, "Value", arcpy.sa.RemapRange([[0, 0.999, 0]]))
    strong.save("strong_lasy")
    fuzzy = arcpy.sa.FuzzyMembership(distLasy, arcpy.sa.FuzzyLinear(17, 100))
    final = arcpy.sa.FuzzyOverlay([strong, fuzzy], "AND")
    final.save("fuzzy_lasy")

def budynki_criterium() -> None:
    distBudynki = "EuCDist_clipped_Budynki"
    max_val = arcpy.management.GetRasterProperties(distBudynki, "MAXIMUM").getOutput(0)
    fuzzy = arcpy.sa.FuzzyMembership(distBudynki, arcpy.sa.FuzzyLinear(152, max_val))
    strong_budynki = arcpy.sa.Reclassify(fuzzy, "Value", arcpy.sa.RemapRange([[0.001, 1, 1]]))
    strong_budynki.save("strong_budynki")
    fuzzy.save("fuzzy_budynki")

def get_slope_and_aspect_from_NMT() -> None:
    raster = "clipped_NMT"
    slope = arcpy.sa.Slope(raster)
    aspect = arcpy.sa.Aspect(raster)
    slope.save("slope_p")
    aspect.save("aspect_p")

def slope_criterium() -> None:
    slope = "slope_p"
    fuzz = arcpy.sa.FuzzyMembership(slope, arcpy.sa.FuzzyLinear(5, 0))
    fuzz = arcpy.sa.Reclassify(fuzz, "Value", arcpy.sa.RemapRange([[0.00001, 1, 1]]))
    fuzz_2 = arcpy.sa.FuzzyMembership(slope, arcpy.sa.FuzzyLinear(10, 0))
    final = arcpy.sa.FuzzyOverlay([fuzz, fuzz_2], "OR")
    final.save("fuzzy_slope")

def aspect_criterium() -> None:
    aspect = "aspect_p"
    remap = arcpy.sa.RemapRange([[-1, -1, 1], [0, 112.5, 0], [112.5, 247.5, 1], [247.5, 360, 0]])
    reclassified = arcpy.sa.Reclassify(aspect, "Value", remap)
    reclassified.save("fuzzy_aspect")

def get_min_from_raster(inRaster: str) -> float:
    minVal = float("inf")
    with arcpy.da.SearchCursor(inRaster, ["Value"]) as cursor:
        for row in cursor:
            v = int(row[0])
            if v != 0 and v < minVal:
                minVal = v
    return minVal

def distance_criterium(distanceToTransportLinksRaster: str, obszar: str) -> None:
    clipped = arcpy.ia.Clip(distanceToTransportLinksRaster, obszar)
    clipped.save("clipped_trans_dist")
    maxVal = int(arcpy.management.GetRasterProperties("clipped_trans_dist", "MAXIMUM").getOutput(0))
    minVal = get_min_from_raster("clipped_trans_dist")
    reclass = arcpy.sa.Reclassify("clipped_trans_dist", "Value", arcpy.sa.RemapRange([[-1, 0, maxVal]]))
    reclass.save("proba")
    final = arcpy.sa.FuzzyMembership(reclass, arcpy.sa.FuzzyLinear(maxVal, minVal))
    final.save("fuzzy_transport_links")

def get_merged_strongs():
    strongCriteria = arcpy.ListRasters("strong*")
    strongAll = arcpy.sa.FuzzyOverlay(strongCriteria, "AND")
    strongAll.save("strong_all")

def get_raster_weights(rasters: List[str], weights: dict[str:float]) -> List:
    return [[raster, "Value", weights[raster]] for raster in rasters if raster in weights]

def get_final_map(weighted: str) -> None:
    allFuzzy = arcpy.ListRasters("fuzzy*")
    PROG = 0.7
    if weighted == "weighted":
        weights = {
        "fuzzy_siec_wodna": 0.15,
        "fuzzy_siec_drogowa": 0.20,
        "fuzzy_lasy": 0.20,
        "fuzzy_budynki": 0.15,
        "fuzzy_slope": 0.10,
        "fuzzy_transport_links": 0.05,
        "fuzzy_aspect": 0.15
        }
    elif weighted == "unweighted":
        weights = {
            "fuzzy_siec_wodna": 1/7,
            "fuzzy_siec_drogowa": 1/7,
            "fuzzy_lasy": 1/7,
            "fuzzy_budynki": 1/7,
            "fuzzy_slope": 1/7,
            "fuzzy_transport_links": 1/7,
            "fuzzy_aspect": 1/7
        }
    raster_weight_list = get_raster_weights(allFuzzy, weights)
    ws_tbl = arcpy.sa.WSTable(raster_weight_list)   
    weighted_sum = arcpy.sa.WeightedSum(ws_tbl) 
    weighted_sum.save(f"fuzzy_all_{weighted}")

    not_normalized_wlc = arcpy.sa.Times(f"fuzzy_all_{weighted}", "strong_all")
    not_normalized_wlc.save(f"not_normalized_wlc_{weighted}")

    maxval = arcpy.management.GetRasterProperties(f"not_normalized_wlc_{weighted}", "MAXIMUM").getOutput(0)
    maxval = float(maxval.replace(',', '.'))

    border = maxval * PROG
    reclass = arcpy.sa.Reclassify(f"not_normalized_wlc_{weighted}", "Value", arcpy.sa.RemapRange([[0, border, 0], [border, maxval, 1]]))
    reclass.save(f"final_mapp_{weighted}")

def distance_between_points(point1, point2):
    point1 = arcpy.PointGeometry(point1)
    point2 = arcpy.PointGeometry(point2)
    return point1.distanceTo(point2)

def prepare_dzialki(dzialki: str, obszar_oryg: str) -> None:
    if not arcpy.ListFeatureClasses("dzialki_s"):
        arcpy.analysis.Intersect(
        in_features=f"{dzialki} #;{obszar_oryg} #",
        out_feature_class="dzialki_s",
        join_attributes="ALL",
        cluster_tolerance=None,
        output_type="INPUT"
        )

def prepare_obszar(obszar_input: str) -> None:
    if not arcpy.ListFeatureClasses("obszar_s"):
         arcpy.analysis.Buffer(obszar_input, "obszar_s", "150 Meters", "FULL", "ROUND", "NONE", None, "PLANAR")
   

def select_dzialki(weighted: str) -> None:
    final_map = f"final_mapp_{weighted}"
    dzialki = "dzialki_s"
    set_null_result = arcpy.sa.SetNull(final_map, final_map, "VALUE = 0")
    useful_polygons = arcpy.conversion.RasterToPolygon(set_null_result, f"polygons_rasterized_{weighted}", "NO_SIMPLIFY")
    summarized = arcpy.analysis.SummarizeWithin(in_polygons=dzialki,in_sum_features=useful_polygons,out_feature_class=f"summarized_in_dzialki_{weighted}", keep_all_polygons="ONLY_INTERSECTING", sum_fields="Shape_Area Sum", sum_shape="ADD_SHAPE_SUM", shape_unit="SQUAREMETERS", group_field=None,add_min_maj="NO_MIN_MAJ", add_group_percent="NO_PERCENT", out_group_table=None)
    layer = arcpy.management.MakeFeatureLayer(in_features=summarized, out_layer=f"useful_dzialki_{weighted}", where_clause="sum_Shape_Area >= Shape_Area * 0.5")
    arcpy.conversion.FeatureClassToGeodatabase(layer, WORKSPACE)

def select_obszar(weighted: str, WORKSPACE) -> None:
    select_dzialki(weighted)
    dzialki_gdb = arcpy.ListFeatureClasses(f"useful_dzialki_{weighted}")[0]
    dzialki_dissolved = arcpy.management.Dissolve(dzialki_gdb, f"dzialki_dissolved_{weighted}", None, None, "SINGLE_PART", None)
    bbox_layer = arcpy.management.MinimumBoundingGeometry(dzialki_dissolved, f"bbox_{weighted}", "RECTANGLE_BY_WIDTH")
    arcpy.management.AddField(bbox_layer, "width", "DOUBLE")

    with arcpy.da.UpdateCursor(bbox_layer, ["SHAPE@", "width"]) as cursor:
        for row in cursor:
            polygon = row[0]
            vertices = [point for point in polygon.getPart(0)]
            if len(vertices) >= 4:
                side_lengths = [
                    distance_between_points(vertices[0], vertices[1]),
                    distance_between_points(vertices[1], vertices[2]),
                    distance_between_points(vertices[2], vertices[3]),
                    distance_between_points(vertices[3], vertices[0])
                ]
                row[1] = min(side_lengths)
            cursor.updateRow(row)
            
    arcpy.management.JoinField(dzialki_dissolved, "OBJECTID", bbox_layer, "OBJECTID", "width")
    dzialki_final = arcpy.management.MakeFeatureLayer(
        in_features=f"dzialki_dissolved_{weighted}",
        out_layer=f"dzialki_final_{weighted}",
        where_clause="Shape_Area >= 20000 And width >= 50"
    )
    arcpy.conversion.FeatureClassToGeodatabase(dzialki_final, WORKSPACE)

def calculate_field_pt(pt_layer: str):
    x_kod_to_cost = {
    "PTWP01": 0, 
    "PTWP02": 200,
    "PTWP03": 0, 
    "PTZB02": 100,
    "PTZB01": 200,
    "PTZB05": 50,
    "PTZB04": 200,
    "PTZB03": 200,
    "PTLZ01": 100,
    "PTLZ02": 50,
    "PTLZ03": 50,
    "PTRK01": 15,
    "PTRK02": 15,
    "PTUT03": 100,
    "PTUT02": 90,
    "PTUT04": 20,
    "PTUT05": 20,
    "PTUT01": 0,  
    "PTTR02": 1,
    "PTTR01": 20,
    "PTKM02": 200,
    "PTKM01": 100,
    "PTKM03": 200,
    "PTKM04": 0,  
    "PTGN01": 1,
    "PTGN02": 1,
    "PTGN03": 1,
    "PTGN04": 1,
    "PTPL01": 50,
    "PTSO01": 0,  
    "PTSO02": 0,  
    "PTWZ01": 0, 
    "PTWZ02": 0, 
    "PTNZ01": 150,
    "PTNZ02": 150
    }
    arcpy.management.AddField(pt_layer, "koszt", "SHORT")

    with arcpy.da.UpdateCursor(pt_layer, ["x_kod", "koszt"]) as cursor:
        for row in cursor:
            x_kod = row[0]
            row[1] = x_kod_to_cost[x_kod]
            cursor.updateRow(row)
    return pt_layer

def get_costraster_pt(pt_layer: str) -> None:
    pt = calculate_field_pt(pt_layer)
    arcpy.conversion.FeatureToRaster(pt, "koszt", "cost_raster_pt", 5)

def get_costmap_pt(weighted: str):
    cost_raster = "cost_raster_pt"
    set_null_result = arcpy.sa.SetNull(cost_raster, cost_raster, "VALUE = 0")
    cost_distance = arcpy.sa.DistanceAccumulation(in_source_data=f"dzialki_final_{weighted}", in_cost_raster=set_null_result, out_back_direction_raster=f"backlink_raster_pt_{weighted}")
    cost_distance.save(f"cost_distance_pt_{weighted}")

def get_dzialka_naj(weighted: str):
    cost_distance = f"cost_distance_pt_{weighted}"
    backlink = f"backlink_raster_pt_{weighted}"
    siec_energetyczna = "clipped_SiecEnergetyczna"
    cost_path = arcpy.sa.CostPath(
        in_destination_data=siec_energetyczna,
        in_cost_distance_raster=cost_distance,
        in_cost_backlink_raster=backlink,
        path_type="BEST_SINGLE",
        destination_field="OBJECTID",
        force_flow_direction_convention="INPUT_RANGE"
    )
    cost_path.save(f"cost_path_energetic_{weighted}")
    dzialki_before_naj = f"dzialki_przed_naj_{weighted}"
    arcpy.management.CopyFeatures(f"dzialki_final_{weighted}", dzialki_before_naj)
    arcpy.conversion.RasterToPolyline(cost_path, "przylacze", "ZERO")
    selected_obszar = arcpy.management.SelectLayerByLocation(
        in_layer=f"dzialki_final_{weighted}",
        overlap_type="INTERSECT",
        select_features="przylacze",
        search_distance=None,
        selection_type="NEW_SELECTION",
        invert_spatial_relationship="NOT_INVERT"
    )
    arcpy.conversion.FeatureClassToGeodatabase(selected_obszar, WORKSPACE)
    
if __name__ == "__main__":
    start = time.time()
    # ----------------- DANE DO UZUPELNIENIA -----------------
    WORKSPACE = r"sciezka/do/geodatabase"
    arcpy.env.workspace = WORKSPACE

    TRAVELTIME_RASTER = arcpy.ListRasters("nazwa_rastra_czasu_dojazdu_do_wezlow_komunikacyjnych_w_bazie_danych")[0]
    OBSZAR_INPUT = "nazwa_warstwy_obszaru_wybranej_gminy_w_bazie_danych"
    DZIALKI_INPUT = "nazwa_warstwy_dzialek_w_bazie_danych"
    PT_INPUT = "nazwa_warstwy_pokrycia_terenu_w_bazie_danych"
    DIRECTORIES = [
        "sciezka(ki)/do/folderu(ow)/bdot10k"
    ]
    RASTER_FOLDER_DIRECTORY = "sciezka/do/folderu/z/rastrami_nmt"
    # ---------------------------------------------------------

    prepare_obszar(OBSZAR_INPUT)
    prepare_dzialki(DZIALKI_INPUT, OBSZAR_INPUT)
    OBSZAR = "obszar_s"
    DZIALKI = "dzialki_s"
    arcpy.env.extent = OBSZAR
    arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(2180)
    arcpy.env.cellSize = 5
    arcpy.env.compression = "LZ77"
    arcpy.env.mask = OBSZAR
    arcpy.env.overwriteOutput = True
    arcpy.env.addOutputsToMap = False

    # Data preparation
    # Rasters
    merge_NMTs(RASTER_FOLDER_DIRECTORY)
    raster = arcpy.Raster(f"{RASTER_FOLDER_DIRECTORY}\merged_raster.tif")
    clip_merged_raster_to_area(raster, OBSZAR)

    # Vectors
    get_layers_from_directories(DIRECTORIES, WORKSPACE)
    featureClasses = arcpy.ListFeatureClasses()
    allCategories = create_categories(featureClasses)
    clip_categories_to_area(allCategories, OBSZAR)
    
    # Analysis
    get_euclidean_distances()

    # Siec drogowa
    drogi_criterium()

    # Siec wodna
    woda_criterium()

    # Lasy
    lasy_criterium()

    # Budynki
    budynki_criterium()

    # Slope and aspect
    get_slope_and_aspect_from_NMT()

    slope_criterium()

    aspect_criterium()

    distance_criterium(TRAVELTIME_RASTER, OBSZAR)

    get_merged_strongs()

    get_final_map("weighted")

    get_final_map("unweighted")

    select_obszar("weighted", WORKSPACE)

    select_obszar("unweighted", WORKSPACE)

    get_costraster_pt(PT_INPUT)

    get_costmap_pt("weighted")

    get_costmap_pt("unweighted")

    get_dzialka_naj("weighted")

    get_dzialka_naj("unweighted")

    end = time.time()
    print(f"Time elapsed: {(end - start) / 60} minutes")