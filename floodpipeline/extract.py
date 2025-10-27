from floodpipeline.secrets import Secrets
from floodpipeline.settings import Settings
from floodpipeline.data import (
    PipelineDataSets,
    DischargeDataUnit,
    BasinDataSet,
    DischargeStationDataUnit,
)
from floodpipeline.load import Load
import os
from datetime import datetime, timedelta
import time
import geopandas as gpd
import pandas as pd
import xarray as xr
from rasterstats import zonal_stats
import rasterio
import logging
import itertools
from typing import List
import urllib.request
import ftplib
import copy 
import glob 
import numpy as np
import xarray as xr
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rioxarray
import shutil
import hydromt_sfincs
 
 
 

supported_sources = ["DELTARES"]


def slice_netcdf_file(nc_file: xr.Dataset, country_bounds: list):
    """Slice the netcdf file to the bounding box"""
    min_lon = country_bounds[0]  # Minimum longitude
    max_lon = country_bounds[2]  # Maximum longitude
    min_lat = country_bounds[1]  # Minimum latitude
    max_lat = country_bounds[3]  # Maximum latitude
    var_data = nc_file.sel(lon=slice(min_lon, max_lon), lat=slice(max_lat, min_lat))
    return var_data


class Extract:
    """Extract river discharge data from external sources"""

    def __init__(
        self,
        settings: Settings = None,
        secrets: Secrets = None,
        data: PipelineDataSets = None,
    ):
        self.source = None
        self.country = None
        self.secrets = None
        self.settings = None
        self.inputPathGrid = "data/input"
        self.outputPathGrid = "data/output"
        self.load = Load()
        if not os.path.exists(self.inputPathGrid):
            os.makedirs(self.inputPathGrid)
        
        if not os.path.exists(self.outputPathGrid):
            os.makedirs(self.outputPathGrid)




        if settings is not None:
            self.set_settings(settings)
            self.load.set_settings(settings)
        if secrets is not None:
            self.set_secrets(secrets)
            self.load.set_secrets(secrets)
        self.data = data

    def set_settings(self, settings):
        """Set settings"""
        if not isinstance(settings, Settings):
            raise TypeError(f"invalid format of settings, use settings.Settings")
        if self.source == "DELTARES":
            settings.check_settings(["DELTARES_FTP_URL"])
        self.settings = settings

    def set_secrets(self, secrets):
        """Set secrets based on the data source"""
        if not isinstance(secrets, Secrets):
            raise TypeError(f"invalid format of secrets, use secrets.Secrets")
        if self.source == "DELTARES":
            secrets.check_secrets(["DELTARES_FTP_USER", "DELTARES_FTP_PASSWORD"])
        self.secrets = secrets

    def set_source(self, source_name, secrets: Secrets = None):
        """Set the data source"""
        if source_name is not None:
            if source_name not in supported_sources:
                raise ValueError(
                    f"Source {source_name} is not supported."
                    f"Supported sources are {', '.join(supported_sources)}"
                )
            else:
                self.source = source_name
                self.inputPathGrid = os.path.join(self.inputPathGrid, self.source)
        else:
            raise ValueError(
                f"Source not specified; provide one of {', '.join(supported_sources)}"
            )
        if secrets is not None:
            self.set_secrets(secrets)
        elif self.secrets is not None:
            self.set_secrets(self.secrets)
        else:
            raise ValueError(f"Set secrets before setting source")
        return self

    def get_data(self, country: str, source: str = None):
        """Get river discharge data from source and return AdminDataSet"""
        if source is None and self.source is None:
            raise RuntimeError("Source not specified, use set_source()")
        elif self.source is None and source is not None:
            self.source = source
        self.country = country
        if self.source == "DELTARES":
            self.prepare_hkvrain_data()
            self.extract_hkvrain_data_nc()
            self.prepare_wflow_data()
            self.extract_wflow_data()           


    


    def prepare_hkvrain_data(self, country: str = None, debug: bool = False):
        """
        download rainfall data from deltares ftp server 
        """
        if country is None:
            country = self.country
        logging.info(f"start preparing rainfall data for country {country}")

        country_gdf = self.load.get_adm_boundaries(country=country, adm_level=1)    
        target_datetime=datetime.today() 
        if debug:
            #target_datetime = (datetime.today() - timedelta(days=1))#.strftime("%Y%m%d")
            target_datetime = datetime.strptime("2025-06-04", "%Y-%m-%d")
        local_file_path = self.inputPathGrid +"/meteorology"

        if not os.path.exists(local_file_path):
            os.makedirs(local_file_path)
        base_dir= 'Meteorology' 

        try:
            self.load.download_forecast_file(
                base_dir,
                local_file_path
                )
        except FileNotFoundError:
            logging.warning(
                f"downloading rainfall data  file failed"
                )   
        logging.info("finished preparing rainfall data")

    def extract_hkvrain_data_tiff(self, country: str = None, debug: bool = False):
        """
   
      
        Compute maximum cumulative rainfall over 1hr, 3hr, and 6hr intervals
        for selected polygons from a shapefile using zonal statistics.

        Args:
            tif_folder (str): Path to folder containing 15-minute interval TIF files.
            shapefile_path (str): Path to the input shapefile or GeoJSON.
            hybas_ids (list): List of HYBAS_IDs to include in the analysis.

        Returns:
            geopandas.GeoDataFrame: Updated GeoDataFrame with max_1hr, max_3hr, max_6hr columns.
        """

        # Helper function: sum rainfall over interval
        def sum_rainfall_stack(start_idx, count):
            stack = []
            for i in range(start_idx, start_idx + count):
                with rasterio.open(tif_files[i]) as src:
                    stack.append(src.read(1))
                    profile = src.profile
            return np.sum(stack, axis=0), profile
        

        # Define intervals in number of 15-min steps
        intervals = {'1hr': 4,'2hr':8, '3hr': 12, '6hr': 24}
        
        if country is None:
            country = self.country
        logging.info(f"start extract rainfall data for country {country}")

        country_gdf = self.load.get_adm_boundaries(country=country, adm_level=1)    
        target_datetime=datetime.today() 
        if debug:
            target_datetime = (datetime.today() - timedelta(days=1))#.strftime("%Y%m%d")
        local_file_path = self.inputPathGrid +"/meteorology"
        # Load and sort TIF files
        tif_files = sorted(glob.glob(os.path.join(local_file_path, "*.tif")))

        tif_folder = local_file_path
        shapefile_path = self.inputPathGrid + "/other/hybas_af_v1c_clipped.geojson"

        #hybas_ids = [1100830330, 1100833680, 1090830330, 1100830840, 1090830320, 1070803250, 1100833460, 1100831050]
        hybas_ids = list(set(int(hybas.hybasid) for hybas in self.data.threshold_basin.data_units))

        # Load and filter shapefile
        gdf = gpd.read_file(shapefile_path)
        gdf = gdf.query("HYBAS_ID in @hybas_ids")    

        # Compute zonal stats
        results = {}
        for label, count in intervals.items():
            zonal_max_per_interval = []
            for i in range(0, len(tif_files) - count + 1):
                sum_array, profile = sum_rainfall_stack(i, count)
                zs = zonal_stats(
                    gdf,
                    sum_array,
                    affine=profile['transform'],
                    stats=["max"],
                    nodata=profile.get('nodata')
                )
                zonal_max_per_interval.append([z["max"] for z in zs])
            results[label] = zonal_max_per_interval

        # Add max values to GeoDataFrame
        for label in results:
            gdf[f"max_{label}"] = np.max(np.array(results[label]), axis=0)
   
        try:
            for data_unit in self.data.threshold_basin.data_units:
                hybas_ids = data_unit.hybasid
                gdf_ = gdf.query("HYBAS_ID == @hybas_ids")
                lead_time = data_unit.lead_time
                # Check if the basin exists in the GeoDataFrame 
                label = f"max_{lead_time}hr"
                if label in results:
                    max_value = gdf_[f"max_{lead_time}hr"]
                    self.data.basin_rainfall.upsert_data_unit(
                        BasinDataSet(
                            hybasid=data_unit.hybasid,
                            hybalevel=data_unit.hybalevel,
                            lead_time=lead_time,
                            pcodes=data_unit.pcodes,
                            rainfall_ensemble=[max_value] if not pd.isna(max_value) else [0.0],
                            )
                        )  

        except FileNotFoundError:
            logging.warning(
                f"extracting rainfall data  file failed"
                )   
        logging.info("finished extracting rainfall data")

    def extract_hkvrain_data_nc(self, country: str = None, debug: bool = False):
            """        
            Compute maximum cumulative rainfall over 1hr, 3hr, and 6hr intervals
            for selected polygons from a shapefile using zonal statistics.

            Args:
                tif_folder (str): Path to folder containing 15-minute interval TIF files.
                shapefile_path (str): Path to the input shapefile or GeoJSON.
                hybas_ids (list): List of HYBAS_IDs to include in the analysis.

            Returns:
                geopandas.GeoDataFrame: Updated GeoDataFrame with max_1hr, max_3hr, max_6hr columns.
            """    
            
            # Define intervals in number of 15-min steps
        
            interval_steps = {'1hr': 4,'2hr':8, '3hr': 12, '6hr': 24} 
            if country is None:
                country = self.country
            logging.info(f"start extract rainfall data for country {country}")
   
            target_datetime=datetime.today() 
       

            if debug:
                #target_datetime = (datetime.today() - timedelta(days=1))#.strftime("%Y%m%d")
                target_datetime = datetime.strptime("2025-06-04", "%Y-%m-%d")
                

            local_file_path = self.inputPathGrid +"/meteorology"

            # Load and sort TIF files
            #nc_files = glob.glob(os.path.join(local_file_path, '*Nowcast_rain*.nc'))

            nc_files = sorted(glob.glob(os.path.join(local_file_path, "*Nowcast_rain*.nc")))


            shapefile_path = self.inputPathGrid + "/other/hybas_af_v1c_clipped.geojson"

            #hybas_ids = [1100830330, 1100833680, 1090830330, 1100830840, 1090830320, 1070803250, 1100833460, 1100831050]

            hybas_ids = list(set(int(hybas.hybasid) for hybas in self.data.threshold_basin.data_units))

            if nc_files:
                #raise FileNotFoundError("No NetCDF file with 'Nowcast_rain' in the name found.")
                #logging.error("No NetCDF file with 'Nowcast_rain' in the name found.")
     
            
                # Load NetCDF with xarray
                nc_path= nc_files[0]  # Assuming you want to process the first file

                ds = xr.open_dataset(nc_path)
                # Adjust variable name below if different
                rain = ds["precip_accumulation"]  # assume shape is (time, y, x) 

                # Load and filter shapefile
                gd = gpd.read_file(shapefile_path)
                gdf = gd.query("HYBAS_ID in @hybas_ids")
                results = {}

                for label, count in interval_steps.items():
                    rain_interval = rain.isel(time=slice(0, count)).sum(dim="time")
                    da_rio = rain_interval.rio.write_crs("EPSG:4326")  # or use the correct CRS

                    max_df={}
                    for hybas_id in hybas_ids:
                        hybas_i = [hybas_id]
                        filtered_gdf1 = gdf.query("HYBAS_ID in @hybas_i") 
                        if not filtered_gdf1.empty:               
                            # Clip raster with shapefile
                            clipped = da_rio.rio.clip(filtered_gdf1.geometry, filtered_gdf1.crs, drop=True, all_touched=True,invert=False)             
                            max_df[hybas_id] = np.nanmax(clipped.values)       
                    results[label] = max_df
                # Add max values to GeoDataFrame
                result_df= pd.DataFrame()

                for label in results:
                    result_df[f"max_{label}"] = np.max(np.array(results[label]), axis=0)

                result_df['HYBAS_ID'] = result_df.index  
                try:
                    for data_unit in self.data.threshold_basin.data_units:
                        hybas_ids = data_unit.hybasid
                        gdf_ = result_df.query("HYBAS_ID == @hybas_ids")
                        for lead_time in [1, 2, 3, 6]: 
                            #lead_time = data_unit.lead_time
                            # Check if the basin exists in the GeoDataFrame 
                            label = f"max_{lead_time}hr"
                            if label in results:
                                max_value = gdf_[f"max_{lead_time}hr"]
                                self.data.basin_rainfall.upsert_data_unit(
                                    BasinDataSet(
                                        hybasid=data_unit.hybasid,
                                        hybalevel=data_unit.hybalevel,
                                        lead_time=lead_time,
                                        pcodes=data_unit.pcodes,
                                        rainfall_ensemble=[max_value] if not pd.isna(max_value) else [0.0],
                                        )
                                    )  
                except FileNotFoundError:
                    logging.warning(
                        f"extracting rainfall data  file failed"
                        )   
                logging.info("finished extracting rainfall data")
            else:
                logging.error("No NetCDF file with 'Nowcast_rain' in the name found.")
        

    def prepare_wflow_data(self, country: str = None, debug: bool = False):
        """
        download rainfall data from deltares ftp server 
        """
        if country is None:
            country = self.country
        logging.info(f"start preparing rainfall data for country {country}")


        target_datetime = datetime.today()#.strftime("%Y%m%d")

        if debug:
            #target_datetime = (datetime.today() - timedelta(days=1))#.strftime("%Y%m%d")      
            target_datetime = datetime.strptime("2025-06-04", "%Y-%m-%d")       

        local_file_path = self.inputPathGrid +"/hydrology"
        subgrid_dem_path = self.inputPathGrid + "/other/dep_subgrid.tif"
       

        if not os.path.exists(local_file_path):
            os.makedirs(local_file_path)

        base_dir= "Hydrology" 
                   
        try:
            self.load.download_forecast_file(
                base_dir,
                local_file_path
                )
            
            # Settings       

            depth_threshold =self.settings.get_setting("minimum_flood_depth")
            flood_var_name = self.settings.get_setting("flood_var_name") # Change this if your variable name is different


            # Find the first NetCDF file with "flood" in the filename
            matches = glob.glob(os.path.join(local_file_path, '*floodmap*.nc'))
            if not matches:
                raise FileNotFoundError("No NetCDF file with 'floodmap' in the name found.")
                
            nc_file = matches[0]
            logging.info(f"Found file: {nc_file}")

            # Open the NetCDF file
            ds = xr.open_dataset(nc_file)
            ds_squeezed = ds.squeeze(dim="realization", drop=True)


            # Ensure the flood depth variable exists
            if flood_var_name not in ds:
                raise KeyError(f"Variable '{flood_var_name}' not found in the dataset.")

            flood = ds_squeezed[flood_var_name]

            # Compute max flood depth lazily (parallelized)
            flood_max = flood.max(dim="time")

            flood_max = flood_max.rio.write_crs("EPSG:32637", inplace=True)       

            flood_mask = flood_max.where(flood_max >= depth_threshold)

            # Trigger actual computation only at the end
            flood_mask = flood_mask.compute()
            
            #Write the crs to the dataArray
            flood.rio.write_crs("EPSG:32637", inplace=True)

            # Load the subgrid DEM
            subgrid_dem_path = self.inputPathGrid + "/other/dep_subgrid.tif"
            with rasterio.open(subgrid_dem_path) as src:
                data = src.read(1)  # read first band
                transform = src.transform
                crs = src.crs
                height, width = data.shape

                # Compute x and y coordinate arrays from affine transform
                x_coords = [transform * (i + 0.5, 0.5) for i in range(width)]
                y_coords = [transform * (0.5, j + 0.5) for j in range(height)]

                # x_coords and y_coords are (x, y) tuples; take the components
                x_coords = [x for x, y in x_coords]
                y_coords = [y for x, y in y_coords]

                # Build DataArray with CRS and transform metadata
                da_dep = xr.DataArray(
                    data,
                    dims=("y", "x"),
                    coords={"x": x_coords, "y": y_coords},
                    attrs={
                        "crs": crs.to_string(),
                        "transform": transform
                    },
                    name="DEM"
                )

                # Enable rioxarray spatial accessors (optional but recommended)
                da_dep = da_dep.rio.write_crs(crs, inplace=True)
                da_dep = da_dep.rio.write_transform(transform, inplace=True)

            # Downscale floodmap to subgrid resolution
            flood_masked = hydromt_sfincs.utils.downscale_floodmap(
                zsmax=flood,
                dep=da_dep,
                hmin=depth_threshold,
                reproj_method = 'bilinear',
            )


            data = np.nan_to_num(flood_masked.values, nan=0.0)

            # Use x and y coordinates
            x = ds['x'].values
            y = ds['y'].values

            # Ensure y is in descending order (top-to-bottom)
            if y[0] < y[-1]:
                y = y[::-1]
                data = data[::-1, :]

            # Calculate resolution
            res_x = (x[-1] - x[0]) / (len(x) - 1)
            res_y = (y[0] - y[-1]) / (len(y) - 1)

            # Define transform and CRS
            src_transform = from_origin(x[0], y[0], res_x, res_y)
            src_crs = 'EPSG:32637'
            dst_crs = 'EPSG:4326'

            # Prepare destination transform and shape
            dst_transform, width, height = calculate_default_transform(
                src_crs, dst_crs, data.shape[1], data.shape[0], *rasterio.transform.array_bounds(data.shape[0], data.shape[1], src_transform)
            )

            # Prepare output array
            dst_data = np.empty((height, width), dtype=data.dtype)

            # Reproject
            reproject(
                source=data,
                destination=dst_data,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest
            )

            # Save to GeoTIFF
            output_tif = self.outputPathGrid + '/flood_extent.tif'

            with rasterio.open(
                output_tif,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=dst_data.dtype,
                crs=dst_crs,
                transform=dst_transform
            ) as dst:
                dst.write(dst_data, 1)



        except FileNotFoundError:
            logging.warning(
                f"downloading hydrology data file failed"
            )        
        logging.info("finished preparing wflow data")

    def extract_wflow_data(self, country: str = None, debug: bool = False):
        """
        download discharge data from deltares ftp server 
        """
        if country is None:
            country = self.country

        logging.info(f"start extracting wflow data for country {country}")   

        target_datetime = datetime.today()#.strftime("%Y%m%d")

        flow_multiplier=1 # Set multiplier for flow values, to simulate triggering of flood alerts

        if debug:
            target_datetime = (datetime.today() - timedelta(days=1))#.strftime("%Y%m%d") 
            #flow_multiplier=1#100000 # Set multiplier for flow values, to simulate triggering of flood alerts for demo
            flow_multiplier =self.settings.get_setting("discharge_multiplier")

        local_file_path = self.inputPathGrid +"/hydrology"
                   
        try:
            local_files = glob.glob(os.path.join(local_file_path, "*wflow*"))          
     
            # Sort files based on timestamp (latest first)
            local_files.sort(reverse=True)

            most_recent_forecast=local_file_path + '/' + os.path.basename(local_files[0])

            ds = xr.open_dataset(most_recent_forecast)
            df = ds.to_dataframe().reset_index()
            df['station_names'] = df['station_names'].str.decode('utf-8')
            #station names have changed in the wflow model, so we need to update them here
            # e.g., dire_dawa to wflow_dire_dawa    
            df['station_names'] = df['station_names'].str.lower().str.replace('dire_dawa', 'wflow_dire_dawa', regex=False)
            df['station_id'] = df['station_id'].str.decode('utf-8') 
            #df['delta'] = df['analysis_time'] - df['time']
            df['delta'] = df['time'] - df['analysis_time']
            df['lead_time'] = df['delta'].dt.total_seconds() / 3600  # Convert to hours 
            df['lead_time'] = df['lead_time'].astype(int)
            df['Q'] = df['Q'] * flow_multiplier  # Apply flow multiplier

            #admin_level=self.data.discharge_admin.adm_levels

            for admin_level in self.data.discharge_admin.adm_levels:
                for data_unit in self.data.threshold_station.data_units:
                    pcodes= data_unit.pcodes[f'{admin_level}']                      
                     
                    st_name = data_unit.station_name

                    logging.info(f"Processing station: {st_name} for admin level {admin_level}")           
                    
                    for lead_time in [1, 2, 3, 6, 12]: 
                        df_station = df.query("station_names == @st_name").query("lead_time <= @lead_time")    
                        max_value =  float(np.nanmax(df_station['Q'].values))

                        self.data.discharge_station.upsert_data_unit(
                            DischargeStationDataUnit(
                                station_code=data_unit.station_code,
                                station_name=data_unit.station_name,
                                pcodes=pcodes,
                                lead_time=lead_time,
                                discharge_ensemble=[max_value],
                            )
                        )             

                        for pcode in pcodes:
                            #logging.info(f"Admin level {admin_level} for leadtime {lead_time} for pcode {pcode} s") 
                            self.data.discharge_admin.upsert_data_unit(
                                DischargeDataUnit(
                                    adm_level=admin_level,
                                    pcode=pcode,
                                    lead_time=lead_time,                       
                                    discharge_ensemble=[max_value],
                                )
                            )         

        except FileNotFoundError:
            logging.warning(
                f"extracting flow data file failed"
            )        
        logging.info("finished preparing wflow data")