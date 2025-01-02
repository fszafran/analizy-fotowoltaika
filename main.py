import arcpy
import re
from typing import List
import os
import time

class Category:
    def __init__(self, name):
        self.name = name
        self.featureList = []
    
    def addFeatureClass(self, featureClass):
        self.featureList.append(featureClass)

def createCategoryList(featureClasses: List[str]) -> List[Category]:
    siecWodna = Category("SiecWodna")
    siecDrogowa = Category("SiecDrogowa")
    lasy = Category("Lasy")
    budynki = Category("Budynki")
    siecEnergetyczna = Category("SiecEnergetyczna")

    for fc in featureClasses:
        if re.search(r"SWRS", fc):
            polygonisedLines = arcpy.analysis.Buffer(fc, f"{fc}_polygon", "1 Meter")
            siecWodna.addFeatureClass(polygonisedLines)
            arcpy.management.Delete(fc)
        elif re.search(r"PTWP", fc):
            siecWodna.addFeatureClass(fc)
        elif re.search(r"SKJZ", fc):
            siecDrogowa.addFeatureClass(fc)
        elif re.search(r"BUBD", fc):
            budynki.addFeatureClass(fc)
        elif re.search(r"PTLZ", fc):
            lasy.addFeatureClass(fc)
        elif re.search(r"SULN", fc):
            siecEnergetyczna.addFeatureClass(fc)
    return [siecWodna, siecDrogowa, lasy, budynki, siecEnergetyczna]

def clipCategoriesToArea(categories: List[Category], area: str) -> None:
    for cat in categories:
        if cat.featureList: 
            mergeOutput = f"merged_{cat.name}"
            clipOutput = f"clipped_{cat.name}"
            merged = arcpy.management.Merge(cat.featureList, mergeOutput)
            arcpy.analysis.Clip(merged, area, clipOutput)

def getEuclideanDistances() -> List[str]:
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


def mergeNMTRasters(rasterFolderDirectory: str) -> None:
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

def clipMergedRasterToArea(mergedRaster: str, area: str) -> None:
    clipped = arcpy.sa.ExtractByMask(
        in_raster=mergedRaster,
        in_mask_data=area,
        extraction_area="INSIDE",
        analysis_extent="#"
    )
    clipped.save("clipped_NMT")
    
def getLayersFromDirectoryList(directories: List[str], environment: str) -> None:
    print("Getting layers from directories")
    patterns = ["OT_SWRS_L", "OT_BUBD_A", "OT_SKJZ_L", "OT_PTWP_A", "OT_PTLZ_A", "OT_SULN_L"]
    paths = prepareFileNames(directories)
    allPT = []
    for path in paths:
        if path.endswith(".shp"):
            if "_PT" in path:
                allPT.append(path)
            if any(pattern in path for pattern in patterns):
                arcpy.conversion.FeatureClassToGeodatabase(path, environment)

    merged = arcpy.management.Merge(allPT, "PT_merged")
    arcpy.analysis.Clip(merged, arcpy.env.mask, "PT_merge_cliped")

def prepareFileNames(directories: List[str]) -> List[str]:
    patterns = ["OT_SWRS_L", "OT_BUBD_A", "OT_SKJZ_L", "OT_PT", "OT_SULN_L"]
    paths = []
    for directory in directories:
        for file in os.listdir(directory):
            if any(pattern in file for pattern in patterns):
                sanitizedPath = sanitizePath(directory, os.path.join(directory, file))
                if sanitizedPath:
                    paths.append(sanitizedPath)
    return paths   

def sanitizePath(directory: str, path: str) -> str:
    parts = path.split("10k.")
    if len(parts) > 1:
        newPath = os.path.join(directory, parts[1])
        os.rename(path, newPath)
        return newPath
    return path

def getFuzzyMemForSiecWodna() -> None:
    distWoda = "EuCDist_clipped_SiecWodna"
    maxVal = arcpy.management.GetRasterProperties(distWoda, "MAXIMUM").getOutput(0)
    first = arcpy.sa.FuzzyMembership(distWoda, arcpy.sa.FuzzyLinear(0, 100))
    first = arcpy.sa.Reclassify(first, "Value", arcpy.sa.RemapRange([[0, 0.999, 0]]))
    first.save("strong_woda")
    second = arcpy.sa.FuzzyMembership(distWoda, arcpy.sa.FuzzyLinear(maxVal, 102))
    final = arcpy.sa.FuzzyOverlay([first, second], "AND")
    final.save("fuzzy_siec_wodna")

def getFuzzyMemForSiecDrogowa() -> None:
    drogi = "clipped_SiecDrogowa"
    density = arcpy.sa.LineDensity(drogi, None, cell_size=5, area_unit_scale_factor="SQUARE_KILOMETERS")
    maxVal = arcpy.management.GetRasterProperties(density, "MAXIMUM").getOutput(0)
    fuzz = arcpy.sa.FuzzyMembership(density, arcpy.sa.FuzzyLinear(0, maxVal))
    fuzz.save("fuzzy_siec_drogowa")

def getFuzzyMemForLasy() -> None:
    distLasy = "EuCDist_clipped_Lasy"
    firstFuzz = arcpy.sa.FuzzyMembership(distLasy, arcpy.sa.FuzzyLinear(0, 15))
    strong_las = arcpy.sa.Reclassify(firstFuzz, "Value", arcpy.sa.RemapRange([[0, 0.999, 0]]))
    strong_las.save("strong_lasy")
    secondFuzz = arcpy.sa.FuzzyMembership(distLasy, arcpy.sa.FuzzyLinear(17, 100))
    final_fuzz = arcpy.sa.FuzzyOverlay([strong_las, secondFuzz], "AND")
    final_fuzz.save("fuzzy_lasy")

def getFuzzyMemForBudynki() -> None:
    distBudynki = "EuCDist_clipped_Budynki"
    maxVal = arcpy.management.GetRasterProperties(distBudynki, "MAXIMUM").getOutput(0)
    first = arcpy.sa.FuzzyMembership(distBudynki, arcpy.sa.FuzzyLinear(152, maxVal))
    strong_budynki = arcpy.sa.Reclassify(first, "Value", arcpy.sa.RemapRange([[0.001, 1, 1]]))
    strong_budynki.save("strong_budynki")
    first.save("fuzzy_budynki")

def getSlopeAndAspectFromNMT(raster: str) -> None:
    slope = arcpy.sa.Slope(raster)
    aspect = arcpy.sa.Aspect(raster)
    slope.save("slope_p")
    aspect.save("aspect_p")

def getFuzzyForSlope(slope: str) -> None:
    fuzz = arcpy.sa.FuzzyMembership(slope, arcpy.sa.FuzzyLinear(5, 0))
    fuzz = arcpy.sa.Reclassify(fuzz, "Value", arcpy.sa.RemapRange([[0.00001, 1, 1]]))
    fuzz2 = arcpy.sa.FuzzyMembership(slope, arcpy.sa.FuzzyLinear(10, 0))
    fuzzfin = arcpy.sa.FuzzyOverlay([fuzz, fuzz2], "OR")
    fuzzfin.save("fuzzy_slope")

def getMapForAspect() -> None:
    aspect = arcpy.ListRasters("aspect_p")[0]
    remap = arcpy.sa.RemapRange([[-1, -1, 1], [0, 112.5, 0], [112.5, 247.5, 1], [247.5, 360, 0]])
    reclassified = arcpy.sa.Reclassify(aspect, "Value", remap)
    reclassified.save("fuzzy_aspect")

def getMinFromRaster(inRaster: str) -> float:
    minVal = float("inf")
    with arcpy.da.SearchCursor(inRaster, ["Value"]) as cursor:
        for row in cursor:
            v = int(row[0])
            if v != 0 and v < minVal:
                minVal = v
    return minVal

def distanceCryterium(distanceToTransportLinksRaster: str, obszar: str) -> None:
    clipped = arcpy.ia.Clip(distanceToTransportLinksRaster, obszar)
    clipped.save("clipped_trans_dist")
    maxVal = int(arcpy.management.GetRasterProperties("clipped_trans_dist", "MAXIMUM").getOutput(0))
    minVal = getMinFromRaster("clipped_trans_dist")
    maxVal += 500
    reclass = arcpy.sa.Reclassify("clipped_trans_dist", "Value", arcpy.sa.RemapRange([[-1, 0, maxVal]]))
    reclass.save("proba")
    fuzz = arcpy.sa.FuzzyMembership(reclass, arcpy.sa.FuzzyLinear(maxVal, minVal))
    fuzz.save("fuzzy_transport_links")

def getMergedStrongs(strongCriteria):
    strongAll = arcpy.sa.FuzzyOverlay(strongCriteria, "AND")
    strongAll.save("all_strong")

def getFinalMap(allFuzzy: List[str], weighted: str) -> None:
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

    theList = []
    for raster in allFuzzy:
        if raster in weights:
            theList.append([raster, "Value", weights[raster]])
    wsTable = arcpy.sa.WSTable(theList)   
    print(wsTable)
    weightedSum = arcpy.sa.WeightedSum(wsTable) 
    weightedSum.save(f"fuzzy_all_{weighted}")

    semifinal = arcpy.sa.Times(f"fuzzy_all_{weighted}", "all_strong")
    semifinal.save(f"fuzzy_all_semifinal_{weighted}")

    maxval = arcpy.management.GetRasterProperties(f"fuzzy_all_semifinal_{weighted}", "MAXIMUM").getOutput(0)
    maxval = float(maxval.replace(',', '.'))

    border = maxval * 0.6
    reclass = arcpy.sa.Reclassify(f"fuzzy_all_semifinal_{weighted}", "Value", arcpy.sa.RemapRange([[0, border, 0], [border, maxval, 1]]))
    reclass.save(f"final_mapp_{weighted}")

def distanceBetweenPoints(point1, point2):
    point1 = arcpy.PointGeometry(point1)
    point2 = arcpy.PointGeometry(point2)
    return point1.distanceTo(point2)

def prepareDzialki(dzialki: str, obszar_oryg: str) -> None:
    arcpy.analysis.Intersect(
    in_features=f"{dzialki} #;{obszar_oryg} #",
    out_feature_class="dzialki_s",
    join_attributes="ALL",
    cluster_tolerance=None,
    output_type="INPUT"
)

def prepareObszar(obszar_input: str) -> None:
    arcpy.analysis.Buffer(obszar_input, "obszar_s", "150 Meters", "FULL", "ROUND", "NONE", None, "PLANAR")

def dealWithDzialki(weighted: str):
    final_map_weighted = f"final_mapp_{weighted}"
    dzialki = "dzialki_s"
    set_null_result = arcpy.sa.SetNull(final_map_weighted, final_map_weighted, "VALUE = 0")
    useful_polygons = arcpy.conversion.RasterToPolygon(set_null_result, f"polygons_rasterized_{weighted}", "NO_SIMPLIFY")
    summarized = arcpy.analysis.SummarizeWithin(in_polygons=dzialki,in_sum_features=useful_polygons,out_feature_class=f"summarized_in_dzialki_{weighted}", keep_all_polygons="ONLY_INTERSECTING", sum_fields="Shape_Area Sum", sum_shape="ADD_SHAPE_SUM", shape_unit="SQUAREMETERS", group_field=None,add_min_maj="NO_MIN_MAJ", add_group_percent="NO_PERCENT", out_group_table=None)
    layer = arcpy.management.MakeFeatureLayer(in_features=summarized, out_layer=f"useful_dzialki_{weighted}", where_clause="sum_Shape_Area >= Shape_Area * 0.5")
    arcpy.conversion.FeatureClassToGeodatabase(layer, WORKSPACE)
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
                    distanceBetweenPoints(vertices[0], vertices[1]),
                    distanceBetweenPoints(vertices[1], vertices[2]),
                    distanceBetweenPoints(vertices[2], vertices[3]),
                    distanceBetweenPoints(vertices[3], vertices[0])
                ]
                row[1] = min(side_lengths)
            cursor.updateRow(row)
            
    arcpy.management.JoinField(dzialki_dissolved, "OBJECTID", bbox_layer, "OBJECTID", "width")
    final = arcpy.management.MakeFeatureLayer(
    in_features=f"dzialki_dissolved_{weighted}",
    out_layer=f"dzialki_final_{weighted}",
    where_clause="Shape_Area >= 20000 And width >= 50"
    )
    arcpy.conversion.FeatureClassToGeodatabase(final, WORKSPACE)

def calculate_field_pt():
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
    pt = "PT_merge_cliped"
    
    arcpy.management.AddField(pt, "koszt", "SHORT")

    with arcpy.da.UpdateCursor(pt, ["X_KOD", "koszt"]) as cursor:
        for row in cursor:
            x_kod = row[0]
            row[1] = x_kod_to_cost[x_kod]
            cursor.updateRow(row)
    return pt

def get_costraster_pt():
    pt = calculate_field_pt()
    arcpy.conversion.FeatureToRaster(pt, "koszt", "cost_raster_pt", 5)

def get_costmap_pt(weighted: str):
    cost_raster = "cost_raster_pt"
    set_null_result = arcpy.sa.SetNull(cost_raster, cost_raster, "VALUE = 0")
    cost_distance = arcpy.sa.DistanceAccumulation(in_source_data=f"dzialki_final_{weighted}", in_cost_raster=set_null_result, out_back_direction_raster=f"backlink_raster_pt_{weighted}")
    cost_distance.save(f"cost_distance_pt_{weighted}")

def get_costpath_energetic(weighted: str):
    cost_distance = f"cost_distance_pt_{weighted}"
    backlink = f"backlink_raster_pt_{weighted}"
    dzialki = f"dzialki_final_{weighted}"
    siec_energetyczna = "clipped_SiecEnergetyczna"
    cost_path = arcpy.sa.CostPath(
        in_destination_data=siec_energetyczna,
        in_cost_distance_raster=cost_distance,
        in_cost_backlink_raster=backlink,
        path_type="BEST_SINGLE",
        destination_field="OBJECTID",
        force_flow_direction_convention="INPUT_RANGE"
    )
    #TODO: wybrać działke ktora intersektuje
    cost_path.save(f"cost_path_energetic_{weighted}")
    
if __name__ == "__main__":
    start = time.time()
    WORKSPACE = r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\cw1\analiz1\MyProject\costam.gdb"
    # r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\cw1\analiz1\MyProject\testowa.gdb"
    OBSZAR_INPUT = "swieradow_zdroj_granice"
    DZIALKI_INPUT = "dzialki_tarnowski"
    DIRECTORIES = [
        # r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\dane_test\powiat_tarnowski_bdot\1216_SHP",
        r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\cw1\bdot_lwowecki",
        r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\cw1\bdot_lubanski"
    ]
    RASTER_FOLDER_DIRECTORY = r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\cw1\nmt_swieradow"
    # r"C:\Users\filo1\Desktop\szkola_sem5\analizy_przestrzenne\dane_test\nmt_tarnow"
    

    arcpy.env.workspace = WORKSPACE
    # prepareObszar(OBSZAR_INPUT)
    # prepareDzialki(DZIALKI_INPUT, OBSZAR_INPUT)
    OBSZAR = "obszar_s"
    DZIALKI = "dzialki_s"
    arcpy.env.extent = OBSZAR
    arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(2180)
    arcpy.env.cellSize = 5
    arcpy.env.compression = "LZ77"
    arcpy.env.mask = OBSZAR
    arcpy.env.overwriteOutput = True
    arcpy.env.addOutputsToMap = False

    TRAVELTIME_RASTER = arcpy.ListRasters("zasieg_fin_tif")[0]
    # Data preparation
    # Rasters
    mergeNMTRasters(RASTER_FOLDER_DIRECTORY)
    raster = arcpy.Raster(f"{RASTER_FOLDER_DIRECTORY}\merged_raster.tif")
    clipMergedRasterToArea(raster, OBSZAR)

    # Vectors
    getLayersFromDirectoryList(DIRECTORIES, WORKSPACE)
    featureClasses = arcpy.ListFeatureClasses()
    allCategories = createCategoryList(featureClasses)
    clipCategoriesToArea(allCategories, OBSZAR)
    
    # Analysis
    getEuclideanDistances()

    # Siec drogowa
    getFuzzyMemForSiecDrogowa()

    # Siec wodna
    getFuzzyMemForSiecWodna()
    
    # Lasy
    getFuzzyMemForLasy()

    # Budynki
    getFuzzyMemForBudynki()

    # Slope and aspect
    getSlopeAndAspectFromNMT("clipped_NMT")
    getFuzzyForSlope("slope_p")
    getMapForAspect()
    distRaster = TRAVELTIME_RASTER
    distanceCryterium(distRaster, OBSZAR)

    strongCriterias = arcpy.ListRasters("strong*")
    getMergedStrongs(strongCriterias)
    allFuzzy = arcpy.ListRasters("fuzzy*")
    getFinalMap(allFuzzy, "weighted")
    getFinalMap(allFuzzy, "unweighted")
    dealWithDzialki("weighted")
    dealWithDzialki("unweighted")
    get_costraster_pt()
    get_costmap_pt("weighted")
    get_costmap_pt("unweighted")
    get_costpath_energetic("weighted")
    get_costpath_energetic("unweighted")
    end = time.time()
    print(f"Time elapsed: {end - start}")