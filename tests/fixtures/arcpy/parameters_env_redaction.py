import arcpy
from arcpy import env


PORTAL_URL = "https://operator:portal-password@example.com/arcgis/rest/services?token=super-token&f=json"
FILE_URL = "file:///home/makani/customer/private.gdb/parcels"
PASSWORD = "plain-text-password"
INPUT_SDE = "/home/makani/customer/private_connection.sde"

input_fc = arcpy.GetParameterAsText(0)
distance = arcpy.GetParameter(1)
env.workspace = r"C:\Users\analyst\customer_project.gdb"
arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Spatial")
arcpy.SetParameterAsText(2, r"C:\Users\analyst\customer_project.gdb\buffered_output")
