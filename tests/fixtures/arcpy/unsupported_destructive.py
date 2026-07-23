import arcpy
from arcpy.sa import Slope


elevation = arcpy.Raster("elevation.tif")
slope = Slope(elevation)
arcpy.management.Delete(r"C:\Users\analyst\scratch.gdb\old_features")
arcpy.SomeMysteryTool("input_features")
