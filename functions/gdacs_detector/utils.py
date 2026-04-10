# t4ds_dev: amorrison@mercycorps.org
# project_partner: Research & Learning, ereid@mercycorps.org
# project_name: AAAStorms
# notes: initial deployment date, 01JUL23; this library supports some specific functions in aaastorms application
#%%
import geopandas as gpd
import shapefile
import zipfile
import io
from shapely import Polygon
import requests
from bs4 import BeautifulSoup

def unzip_shapefile(url):
    r = requests.get(url)
    if r.status_code == 200:
        zip = zipfile.ZipFile(io.BytesIO(r.content),'r')
        gdf = read_shapefile(zip)
        return gdf
    else: raise ValueError(f'Bad status code {r.status_code}')

def read_shapefile(zipshape):
    """
    Read a shapefile into a Pandas dataframe with a 'coords' 
    column holding the geometry information. This uses the pyshp
    package
    """
    names = []
    for name in zipshape.namelist():
        if 'png' in name:
            names.append(name)
    sf_shape = shapefile.Reader(shp=io.BytesIO(zipshape.read([x for x in zipshape.namelist() if 'pgn.shp' in x][0])),
                     shx=io.BytesIO(zipshape.read([x for x in zipshape.namelist() if 'pgn.shx' in x][0])),
                     dbf=io.BytesIO(zipshape.read([x for x in zipshape.namelist() if 'pgn.dbf' in x][0])))
    fields = [x[0] for x in sf_shape.fields][1:]
    records = [y[:] for y in sf_shape.records()]
    shps = [s.points for s in sf_shape.shapes()]
    gdf = gpd.GeoDataFrame(columns=fields, data=records, geometry=[Polygon(x) for x in shps])
    return gdf

def make_soup(shtml):
    """
    Read a shtml website text and return text for
    """
    r = requests.get(shtml).text
    soup = BeautifulSoup(r, "html.parser")
    return soup

#%%
