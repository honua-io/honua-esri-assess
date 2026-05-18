import arcpy as gp
from arcpy.analysis import Clip
from arcpy.management import Project


input_fc = gp.GetParameterAsText(0)
clip_fc = gp.GetParameterAsText(1)

buffered = gp.analysis.Buffer(input_fc, "memory/buffered", "10 Meters")
intersected = gp.Intersect_analysis([buffered, "roads.shp"], "memory/intersected")
clipped = Clip(intersected, clip_fc, "memory/clipped")
Project(clipped, "memory/projected", "EPSG:4326")
