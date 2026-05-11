from __future__ import annotations

import os.path
import copy
import time

from floodpipeline.secrets import Secrets
from floodpipeline.settings import Settings
from floodpipeline.data import (
    AdminDataSet,
    AdminDataUnit,
    BasinDataUnit,
    BasinDataSet,
    DischargeDataUnit,
    ForecastDataUnit,
    ThresholdDataUnit,
    StationDataUnit,
    StationDataSet,
    ThresholdStationDataUnit,
    ForecastStationDataUnit,
    ForecastBasinDataUnit,
    DischargeStationDataUnit,
    RainfallBasinDataUnit,
    ThresholdBasinDataUnit,
    PipelineDataSets,
)
from urllib.error import HTTPError
import urllib.request, json
from datetime import datetime, timedelta, date
import azure.cosmos.cosmos_client as cosmos_client
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests
import geopandas as gpd
from typing import List
import shutil
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

from ftplib import FTP_TLS
import os
import re
import shutil



COSMOS_DATA_TYPES = [
    "basin",
    "basin-rainfall",
    "discharge",
    "discharge-station",
    "forecast",
    "forecast-basin",
    "forecast-station",
    "threshold",
    "threshold-basin",
    "threshold-station"
]


def get_cosmos_query(
    start_date=None,
    end_date=None,
    country=None,
    adm_level=None,
    pcode=None,
    hybasid=None,
    lead_time=None,
):
    filters = []

    if start_date is not None:
        filters.append(f'c.timestamp >= "{start_date.strftime("%Y-%m-%dT%H:%M:%S")}"')
    if end_date is not None:
        filters.append(f'c.timestamp <= "{end_date.strftime("%Y-%m-%dT%H:%M:%S")}"')
    if country is not None:
        filters.append(f'c.country = "{country}"')
    if adm_level is not None:
        filters.append(f'c.adm_level = "{adm_level}"')
    if pcode is not None:
        filters.append(f'c.pcode = "{pcode}"')
    if lead_time is not None:
        filters.append(f'c.lead_time = "{lead_time}"')
    if hybasid is not None:
        filters.append(f'c.hybasid = "{hybasid}"')
    if filters:
        query = "SELECT * FROM c WHERE " + " AND ".join(filters)
    else:
        query = "SELECT * FROM c"

    return query









 




def get_data_unit_id(data_unit: AdminDataUnit, dataset: AdminDataSet):
    """Get data unit ID"""
    if hasattr(data_unit, "pcode"):
        if hasattr(data_unit, "lead_time"):
            id_ = f"{data_unit.pcode}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}_{data_unit.lead_time}"
        else:
            id_ = f"{data_unit.pcode}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"
    elif hasattr(data_unit, "station_code"):
        if hasattr(data_unit, "lead_time"):
            id_ = f"{data_unit.station_code}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}_{data_unit.lead_time}"
        else:
            id_ = f"{data_unit.station_code}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"
    elif hasattr(data_unit, "hybasid"):
        if hasattr(data_unit, "lead_time"):
            id_ = f"{data_unit.hybasid}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}_{data_unit.lead_time}"
        else:
            id_ = f"{data_unit.hybasid}_{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"
    else:
        id_ = f"{dataset.timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"
    return id_


def alert_class_to_threshold(alert_class: str, triggered: bool) -> float:
    """Convert alert class to 'alert_threshold'"""
    if alert_class == "no":
        return 0.0
    elif alert_class == "min":
        return 0.3
    elif alert_class == "med":
        return 0.7
    elif alert_class == "max":
        if triggered:
            return 1.0
        else:
            return 0.7
    else:
        raise ValueError(f"Invalid alert class {alert_class}")


def forecast_trigger_status(triggered: bool, trigger_class: str):
    """determine if forecast is a trigger for IBF portal if trigger status is true and trigger activation is enabled in config file the 
        trigger staus will be 1 , else 0"""
    if triggered:
        if trigger_class == "enabled":
            return 1
        else:
            return 0
    else:
        return 0 



class Load:
    """Download/upload data from/to a data storage"""

    def __init__(self, settings: Settings = None, secrets: Secrets = None):
        self.secrets = None
        self.settings = None
        if settings is not None:
            self.set_settings(settings)
        if secrets is not None:
            self.set_secrets(secrets)
        self.rasters_sent = []

    def set_settings(self, settings):
        """Set settings"""
        if not isinstance(settings, Settings):
            raise TypeError(f"invalid format of settings, use settings.Settings")
        settings.check_settings(
            ["postgresql_server", "postgresql_port", "postgresql_database"]
        )
        self.settings = settings

    def set_secrets(self, secrets):
        """Set secrets for storage"""
        if not isinstance(secrets, Secrets):
            raise TypeError(f"invalid format of secrets, use secrets.Secrets")
        secrets.check_secrets(
            [
                "COSMOS_URL",
                "COSMOS_KEY",
                "BLOB_ACCOUNT_NAME",
                "BLOB_ACCOUNT_KEY",
                "IBF_API_URL",
                "IBF_API_USER",
                "IBF_API_PASSWORD",
            ]
        )
        self.secrets = secrets



    def extract_start_time(self, filename):
        """
        Extract timestamps (start and optional secondary) from filename.

        Supports:
            - YYYYMMDD_HHMM   → e.g. 20251006_0730
            - YYYYMMDDTHHMMSS → e.g. 20251006T073000

        Returns:
            dict: {
                'start_time': datetime or None,
                'secondary_time': datetime or None,
                'all_times': [list of all parsed datetime objects]
            }
        """
        # Match either YYYYMMDD_HHMM or YYYYMMDDTHHMMSS
        timestamp_pattern = r'\d{8}[_T]\d{4,6}'
        matches = re.findall(timestamp_pattern, filename)

        parsed_times = []
        
        for ts in matches:
            try:
                if 'T' in ts:
                    # Format like 20251006T073000
                    parsed_times.append(datetime.strptime(ts, "%Y%m%dT%H%M%S"))
                elif '_' in ts:
                    # Format like 20251006_0730 or 20251006_073000
                    fmt = "%Y%m%d_%H%M" if len(ts.split('_')[1]) == 4 else "%Y%m%d_%H%M%S"
                    parsed_times.append(datetime.strptime(ts, fmt))
            except ValueError:
                continue

        start_time = parsed_times[0] if len(parsed_times) >= 1 else None
        secondary_time = parsed_times[1] if len(parsed_times) >= 2 else None

        return start_time 


    def get_latest_file(self, file_list):
        """Return the file with the latest start timestamp."""

        dated_files = [
            (f, self.extract_start_time(f))
            for f in file_list
            if self.extract_start_time(f)
        ]
        if not dated_files:
            return None
        latest_file = max(dated_files, key=lambda x: x[1])[0]
        return latest_file

    def get_latest_file_from_dict(self, file_dict):
        """Return the file with the latest start timestamp."""
        latestfile_dict={}

        for file_key,file_list in file_dict.items():
 
            dated_files = [
                (f, self.extract_start_time(f))
                for f in file_list
                if self.extract_start_time(f)
            ]

            if not dated_files:
                continue
            latest_file = max(dated_files, key=lambda x: x[1])[0]
            localfilenam= max(dated_files, key=lambda x: x[1])[1]  

            localfilename=file_key+ f"_{localfilenam.strftime('%Y%m%d%H%M')}.nc"
            latestfile_dict[file_key]=[localfilename, latest_file]  

        return latestfile_dict

       



    def download_forecast_file(self,
        base_dir: str,
        save_path: str,
    ):
        """
        Downloads the latest available file from Deltares FTPS server based on the file pattern and timestamp.
        Args:
            base_dir (str): Root directory on the server, e.g., "Hydrology"
            file_pattern (str): Substring in the file name to match (e.g., "floodmap")
            target_datetime (datetime): Date and time to locate the file folder
            save_path (str): Local path to save the downloaded file
        """
        timestamp_pattern = r'\d{8}T\d{6}'  # Matches the format YYYYMMDDTHHMMSS

        host = self.secrets.get_secret("DELTARES_FTP_URL")
        ftps = FTP_TLS()
        ftps.connect(host=host, port=990)  # Explicitly specify port  

        ftps.login(
            user=self.secrets.get_secret("DELTARES_FTP_USER"),
            passwd=self.secrets.get_secret("DELTARES_FTP_PASSWORD")
        )

        ftps.prot_p()  # Switch to secure data connection

        #subfolder = target_datetime.strftime("%Y%m%d")
        folder_path = f"/{base_dir}"

        logging.info(f"Navigating to {folder_path}")
        try:
            ftps.cwd(folder_path)
            files = ftps.nlst()

            if not files:
                logging.warning("No files found in directory.")
                return
            
            # Filter observation and nowcast files
            if base_dir=="Meteorology":
                obs_files = [f for f in files if "Observation" in f ]
                now_files = [f for f in files if "Nowcast" in f ]
                fname_annex=["Observation_rain","Nowcast_rain"]
                files_dict={"Observation_rain":obs_files,"Nowcast_rain":now_files}  
            elif base_dir=="Hydrology":
                obs_files = [f for f in files if "floodmap" in f and "forecast" in f]
                now_files = [f for f in files if "wflow" in f and "forecast" in f]
                fname_annex=["floodmap","wflow"]
                files_dict={"floodmap":obs_files,"wflow":now_files}
            else:
                logging.error("Correct directory should be specified to find files.")
                return


            latest_obs = self.get_latest_file(obs_files)
            latest_now = self.get_latest_file(now_files)

            # [localfilename, latest_file]
            latest_files_dict=self.get_latest_file_from_dict(files_dict)
            for key, value in latest_files_dict.items():
                logging.info(f"Latest file for {key}: {value[1]} with local filename {value[0]}")  
                local_file_path = os.path.join(save_path, value[0])
                logging.info(f"Downloading latest {key} file: {value[1]} → {local_file_path}")

                with open(local_file_path, 'wb') as f:
                    ftps.retrbinary(f"RETR {value[1]}", f.write)

                logging.info(f"{key} file download complete: {value[1]}")

            ''' 
            for label, file in [(fname_annex[0], latest_obs), (fname_annex[1], latest_now)]:
                if not file:
                    logging.warning(f"No {label} file found.")
                    continue

                local_file_path = os.path.join(save_path, label+".nc")
                logging.info(f"Downloading latest {label} file: {file} → {local_file_path}")

                with open(local_file_path, 'wb') as f:
                    ftps.retrbinary(f"RETR {file}", f.write)

                logging.info(f"{label} file download complete: {file}")
            '''

        except Exception as e:
            logging.warning(f"Failed to download: {e}")
        finally:
            ftps.quit()

    def get_population_density(self, country: str, file_path: str):
        """Get population density data from worldpop and save to file_path"""
        r = requests.get(
            f"{self.settings.get_setting('worldpop_url')}/{country.upper()}/{country.lower()}_ppp_2020_UNadj_constrained.tif" 
            #f"{self.settings.get_setting('worldpop_url')}/{country.upper()}/{country.lower()}_ppp_2022_1km_UNadj_constrained.tif"
        )
        if "404 Not Found" in str(r.content):
            raise FileNotFoundError(
                f"Population density data not found for country {country}"
            )
        with open(file_path, "wb") as file:
            file.write(r.content)

    def get_adm_boundaries(self, country: str, adm_level: int) -> gpd.GeoDataFrame:
        """Get admin areas from IBF API"""
        try:
            adm_boundaries = self.ibf_api_get_request(
                f"admin-areas/{country}/{adm_level}",
            )
            gdf_adm_boundaries = gpd.GeoDataFrame.from_features(
                adm_boundaries["features"]
            )
            gdf_adm_boundaries.set_crs(epsg=4326, inplace=True)
        except HTTPError:
            raise FileNotFoundError(
                f"Admin areas for country {country}"
                f" and admin level {adm_level} not found"
            )
        return gdf_adm_boundaries

    def __ibf_api_authenticate(self):
        no_attempts, attempt, login_response = 5, 0, None
        while attempt < no_attempts:
            try:
                login_response = requests.post(
                    self.secrets.get_secret("IBF_API_URL") + "user/login",
                    data=[
                        ("email", self.secrets.get_secret("IBF_API_USER")),
                        ("password", self.secrets.get_secret("IBF_API_PASSWORD")),
                    ],
                )
                break
            except requests.exceptions.ConnectionError:
                attempt += 1
                logging.warning(
                    "IBF API currently not available, trying again in 1 minute"
                )
                time.sleep(60)
        if not login_response:
            raise ConnectionError("IBF API not available")
        return login_response.json()["user"]["token"]

    def ibf_api_post_request(self, path, body=None, files=None):
        token = self.__ibf_api_authenticate()
        if body is not None:
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        elif files is not None:
            headers = {"Authorization": "Bearer " + token}
        else:
            raise ValueError("No body or files provided")
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        r = session.post(
            self.secrets.get_secret("IBF_API_URL") + path,
            json=body,
            files=files,
            headers=headers,
        )
        if r.status_code >= 400:
            raise ValueError(
                f"Error in IBF API POST request: {r.status_code}, {r.text}"
            )
        if not os.path.exists("logs"):
            os.makedirs("logs")
        if body:
            filename = body["date"]
            filename = "".join(x for x in filename if x.isalnum())
            filename = filename + ".json"
            filename = os.path.join("logs", filename)
            logs = {"endpoint": path, "payload": body}
            with open(filename, "a") as file:
                file.write(str(logs) + "\n")
        elif files:
            filename = datetime.today().strftime("%Y%m%d") + ".json"
            filename = os.path.join("logs", filename)
            logs = {"endpoint": path, "payload": files}
            with open(filename, "a") as file:
                file.write(str(logs) + "\n")

    def ibf_api_get_request(self, path, parameters=None):
        token = self.__ibf_api_authenticate()
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "*/*",
        }
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        r = session.get(
            self.secrets.get_secret("IBF_API_URL") + path,
            headers=headers,
            params=parameters,
        )
        if r.status_code >= 400:
            raise ValueError(f"Error in IBF API GET request: {r.status_code}, {r.text}")
        return r.json()

    def get_stations(self, country: str) -> list[dict]:
        """Get GloFAS stations from IBF app"""
        stations = self.ibf_api_get_request(
            f"point-data/gauges/{country}",
            parameters={
                "disasterType": "flash-floods",#flash-floods
                "pointDataCategory": "gauges",
                "countryCodeISO3": country,
            },
        )
        gdf_stations = gpd.GeoDataFrame.from_features(stations["features"])
        stations = []
        for ix, row in gdf_stations.iterrows():
            station = {
                "stationCode": row["stationCode"],
                "stationName": row["stationName"],
                "lat": row["geometry"].y,
                "lon": row["geometry"].x,
            }
            stations.append(station)

        return stations

    def send_to_ibf_api(
        self,
        forecast_data: AdminDataSet,
        discharge_data: AdminDataSet,
        forecast_station_data: StationDataSet,
        discharge_station_data: StationDataSet,
        flood_extent: str = None,
        upload_time: str = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    ):
        """Send flood forecast data to IBF API"""

        country = forecast_data.country 
        logging.info(f"Sending data to IBF API for country {country} at {upload_time}")



        trigger_on_lead_time = self.settings.get_country_setting(
            country, "trigger-on-lead-time"
        )
        trigger_on_return_period = self.settings.get_country_setting(
            country, "trigger-on-return-period"
        )
        threshold_station_data = self.get_pipeline_data(
            data_type="threshold-station", country=country
        )

        

        adm_levels=self.settings.get_country_setting(country, "admin-levels")

        disasterType= self.settings.get_setting('disaster_type')  # "flash-floods"
        pipeline_will_trigger_portal = self.settings.get_country_setting(country, "pipeline-will-trigger-portal") 


        processed_stations, processed_pcodes, triggered_lead_times = [], [], []

        event_id = datetime.strptime(upload_time, "%Y-%m-%dT%H:%M:%SZ")
        event_id = event_id.strftime("%Y%m%d%H")


        logging.info("Sending data to IBF API for country  1")

        # START EVENT LOOP
        for station_code in forecast_station_data.get_station_codes():
            logging.info(f"Sending data to IBF API for country  station {station_code}")

            # determine events
            events = {}
            for lead_time in [1,2,3,6]:
                if (
                    forecast_station_data.get_data_unit(
                        station_code, lead_time
                    ).alert_class
                    != "no"
                ):
                    events[lead_time] = "alert"


            for lead_time in [1,2,3,6]:
                if forecast_station_data.get_data_unit(
                    station_code, lead_time
                ).triggered:
                    events[lead_time] = "trigger"
                    triggered_lead_times.append(lead_time)

            ###########################
            #  flash flood portal currently accept only trigger therefore we filter out alerts 
            trigger_events = {}

            for key, value in events.items():
                if key not in trigger_events and value == "trigger":
                    trigger_events[key] = value


            if not trigger_events:
                continue

            events = dict(sorted(trigger_events.items()))
            

            for lead_time_event, event_type in events.items():

                # set as alert if lead time is greater than trigger_on_lead_time
                if lead_time_event > trigger_on_lead_time and event_type == "trigger":
                    event_type = "alert"
                station_name = forecast_station_data.get_data_unit(
                    station_code, trigger_on_lead_time
                ).station_name

                event_name = "Dire Dawa urban"

                if event_name == "" or event_name == "None" or event_name == "Na":
                    event_name = str(station_code)

                logging.info(
                    f"event {event_name}, type '{event_type}', lead time {lead_time_event}"
                )
                forecast_station = forecast_station_data.get_data_unit(
                    station_code, lead_time_event
                )
                threshold_station = threshold_station_data.get_data_unit(station_code)

                # send exposure data: admin-area-dynamic-data/exposure
                indicators = [
                    "population_affected",
                    #"population_affected_percentage",
                    #"alert_threshold",
                    "forecast_trigger",
                    "forecast_severity",
                ]

                for indicator in indicators:
                    for adm_level in adm_levels: #forecast_station.pcodes.keys(): uploading data only for admin level 3 
                        exposure_pcodes = []
                        logging.info(f"Sending data to IBF API for country {country} indicator {indicator} admin level {forecast_station.pcodes}")
                        for pcode in forecast_station.pcodes:
                        #for pcode in forecast_station.pcodes[f'{adm_level}']:                        
                            forecast_admin = forecast_data.get_data_unit(
                                pcode, lead_time_event
                            )
                            amount = None
                            if indicator == "population_affected":
                                amount = forecast_admin.pop_affected
                            elif indicator == "population_affected_percentage":
                                amount = forecast_admin.pop_affected_perc
                            elif indicator == "forecast_severity":
                                amount = (1 if forecast_admin.triggered else 0) #forecast_admin.triggered # ( 1 if event_type == "trigger" else 0 )
                            elif indicator == "forecast_trigger":
                                amount = forecast_trigger_status(
                                    triggered=(True if event_type == "trigger" else False),
                                    #triggered= (forecast_admin.triggered > 0),# True if event_type == "trigger" else False   ),
                                    trigger_class=pipeline_will_trigger_portal,
                                    )
                            #elif indicator == "alert_threshold":
                            #    amount = alert_class_to_threshold(alert_class=forecast_admin.alert_class, triggered=(True if event_type == "trigger" else False),)
                            exposure_pcodes.append(
                                {"placeCode": pcode, "amount": amount}
                            )
                            processed_pcodes.append(pcode)
                        body = {
                            "countryCodeISO3": country,
                            "leadTime": f"{lead_time_event}-hour",
                            "dynamicIndicator": indicator,
                            "adminLevel": int(adm_level),
                            "exposurePlaceCodes": exposure_pcodes,
                            "disasterType": disasterType,
                            "eventName": event_name,
                            "date": upload_time,
                        }
                        logging.info(f"Sending data to IBF API for country {country} indicator {indicator}  lead time {lead_time_event}-hour admin level {adm_level} event name {event_name}")

                        statsPath=flood_extent.replace(".tif", f"_{event_name}_{lead_time_event}-hour_{country}_{adm_level}.json" )

                        statsPath=statsPath.replace("extent", f"{indicator}")

                        with open(statsPath, 'w') as fp:
                            json.dump(body, fp)


                        self.ibf_api_post_request(
                            "admin-area-dynamic-data/exposure", body=body
                        )
                processed_pcodes = list(set(processed_pcodes))

                # GloFAS station data: point-data/dynamic
                # 1 call per alert/triggered station, and 1 overall (to same endpoint) for all other stations
                if event_type != "none":
                    station_forecasts = {
                        "forecastLevel": [],
                        "eapAlertClass": [],
                        "forecastReturnPeriod": [],
                        "triggerLevel": [],
                        "water-level": [],
                        "water-level-reference": [],
                        "water-level-previous": [],
                        "water-level-alert-level":[],
                    }

                    discharge_station = discharge_station_data.get_data_unit(
                        station_code, lead_time_event
                    )
                    for indicator in station_forecasts.keys():
                        value = None
                        if indicator == "forecastLevel":
                            value = int(discharge_station.discharge_mean or 0)
                        elif indicator == "eapAlertClass":
                            value = forecast_station.alert_class
                            if event_type == "alert" and value == "max":
                                value = "med"
                        elif indicator == "forecastReturnPeriod":
                            value = forecast_station.return_period
                        elif indicator == "triggerLevel":
                            value = int(
                                threshold_station.get_threshold(
                                    trigger_on_return_period
                                )
                            )
                        elif indicator == "water-level-reference":
                            value = int(
                                threshold_station.get_threshold(
                                    trigger_on_return_period
                                )
                            )
                        elif indicator == "water-level-previous":
                            value = 0
                        elif indicator == "water-level":
                            value = int(discharge_station.discharge_mean or 0)
                        elif indicator == "water-level-alert-level":
                            value = forecast_station.alert_class
                            if event_type == "alert" and value == "max":
                                value = "trigger"
                            elif event_type == "alert" and value =="med":
                                value = "warning-medium"
                            elif event_type == "alert" and value == "min":
                                value = "warning-low"
                            else:
                                value = "none"


                        station_data = {"fid": station_code[-1], "value": value}
                        station_forecasts[indicator].append(station_data)
                        body = {
                            "countryCodeISO3": country,
                            "leadTime": f"{lead_time_event}-hour",
                            "key": indicator,
                            "dynamicPointData": station_forecasts[indicator],
                            "pointDataCategory": "gauges",
                            "disasterType": disasterType,
                            "date": upload_time,
                        }
                        self.ibf_api_post_request("point-data/dynamic", body=body)

                        statsPath=flood_extent.replace(".tif", f"_{lead_time_event}-hour_{country}.json" )
                        statsPath=statsPath.replace("extent", f"{indicator}")

                        with open(statsPath, 'w') as fp:
                            json.dump(body, fp)

                    processed_stations.append(station_code)

            # send trigger per lead time: event/triggers-per-leadtime
            triggers_per_lead_time = []
            for lead_time in [1,2,3,6]:# range(0, 8):
                is_trigger, is_trigger_or_alert = False, False
                for lead_time_event, event_type in events.items():
                    if event_type == "trigger" and lead_time >= lead_time_event:
                        is_trigger = True
                    if (
                        event_type == "trigger" or event_type == "alert"
                    ) and lead_time >= lead_time_event:
                        is_trigger_or_alert = True
                triggers_per_lead_time.append(
                    {
                        "leadTime": f"{lead_time}-day",
                        "triggered": is_trigger_or_alert,
                        "thresholdReached": is_trigger,
                    }
                )
            body = {
                "countryCodeISO3": country,
                "triggersPerLeadTime": triggers_per_lead_time,
                "disasterType": disasterType,
                "eventName": event_name,
                "date": upload_time,
            }
            self.ibf_api_post_request("event/triggers-per-leadtime", body=body)

        # END OF EVENT LOOP
        ###############################################################################################################

        # flood extent raster: admin-area-dynamic-data/raster/floods
        self.rasters_sent = []
        logging.info("Sending data to IBF API for country  no event")
        for lead_time in [1,2,3,6]: # range(0, 8):
            flood_extent_new = flood_extent.replace(
                ".tif", f"_{lead_time}-hour_{country}.tif"
            )
            if lead_time in triggered_lead_times:
                shutil.copy(
                    flood_extent.replace(".tif", f"_{lead_time}.tif"), flood_extent_new
                )
            else:
                shutil.copy(
                    flood_extent.replace(".tif", f"_empty.tif"),
                    flood_extent_new,
                )
            self.rasters_sent.append(flood_extent_new)
            files = {"file": open(flood_extent_new, "rb")}
            self.ibf_api_post_request(
                "admin-area-dynamic-data/raster/floods", files=files
            )

        # send empty exposure data
        if len(processed_pcodes) == 0:
            indicators = [
                "population_affected",
                #"population_affected_percentage",
                #"alert_threshold",
                "forecast_trigger",
                "forecast_severity",
            ]
            for indicator in indicators:
                for adm_level in forecast_data.adm_levels:
                    exposure_pcodes = []
                    for pcode in forecast_data.get_pcodes(adm_level=adm_level):
                        if pcode not in processed_pcodes:
                            amount = None
                            if indicator == "population_affected":
                                amount = 0
                            elif indicator == "population_affected_percentage":
                                amount = 0.0
                            elif indicator == "forecast_trigger":
                                amount = 0
                            elif indicator == "forecast_severity":
                                amount = 0
                            elif indicator == "alert_threshold":
                                amount = 0.0
                            exposure_pcodes.append(
                                {"placeCode": pcode, "amount": amount}
                            )

                    logging.info(f"Sending data to IBF API for country  no data indicator {indicator}")
                    body = {
                        "countryCodeISO3": country,
                        "leadTime": "1-hour",  # this is a specific check IBF uses to establish no-trigger
                        "dynamicIndicator": indicator,
                        "adminLevel": adm_level,
                        "exposurePlaceCodes": exposure_pcodes,
                        "disasterType": disasterType,
                        "eventName": None,  # this is a specific check IBF uses to establish no-trigger
                        "date": upload_time,
                    }
                    self.ibf_api_post_request(
                        "admin-area-dynamic-data/exposure", body=body
                    )
                    logging.info(f"finished Sending data to IBF API for country  no data indicator {indicator}")

        # send GloFAS station data for all other stations
        station_forecasts = {
            "forecastLevel": [],
            "eapAlertClass": [],
            "forecastReturnPeriod": [],
            "triggerLevel": [],
        }

        for indicator in station_forecasts.keys():
            for station_code in forecast_station_data.get_station_codes():
                if station_code not in processed_stations:
                    discharge_station = discharge_station_data.get_data_unit(
                        station_code, trigger_on_lead_time
                    )
                    forecast_station = forecast_station_data.get_data_unit(
                        station_code, trigger_on_lead_time
                    )
                    threshold_station = threshold_station_data.get_data_unit(
                        station_code
                    )
                    value = None
                    if indicator == "forecastLevel":
                        value = int(discharge_station.discharge_mean or 0)
                    elif indicator == "eapAlertClass":
                        value = forecast_station.alert_class
                    elif indicator == "forecastReturnPeriod":
                        value = forecast_station.return_period
                    elif indicator == "triggerLevel":
                        value = int(
                            threshold_station.get_threshold(trigger_on_return_period)
                        )
                    station_data = {"fid": station_code[-1], "value": value}
                    station_forecasts[indicator].append(station_data)

            body = {
                "countryCodeISO3": country,
                "leadTime": f"1-hour",
                "key": indicator,
                "dynamicPointData": station_forecasts[indicator],
                "pointDataCategory": "gauges",
                "disasterType": disasterType,
                "date": upload_time,
            }
            self.ibf_api_post_request("point-data/dynamic", body=body)
            logging.info(f"finished Sending guage data to IBF API for country  no data indicator {indicator}")

        # send notification
        body = {
            "countryCodeISO3": country,
            "disasterType": disasterType,
            "date": upload_time,
        }
        self.ibf_api_post_request("events/process", body=body)
 

    def save_pipeline_data(
        self, data_type: str, dataset: AdminDataSet, replace_country: bool = False
    ):
        """Upload pipeline datasets to Cosmos DB"""
        if data_type not in COSMOS_DATA_TYPES:
            raise ValueError(
                f"Data type {data_type} is not supported."
                f"Supported storages are {', '.join(COSMOS_DATA_TYPES)}"
            )
        # check data types
        if data_type == "discharge":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, DischargeDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type DischargeDataUnit"
                    )
        elif data_type == "forecast":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ForecastDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ForecastDataUnit"
                    )
        elif data_type == "threshold":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ThresholdDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ThresholdDataUnit"
                    )
        elif data_type == "discharge-station":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, DischargeStationDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type DischargeStationDataUnit"
                    )
        elif data_type == "forecast-station":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ForecastStationDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ForecastStationDataUnit"
                    )
        elif data_type == "threshold-station":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ThresholdStationDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ThresholdStationDataUnit"
                    )
        elif data_type == "threshold-basin":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ThresholdBasinDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ThresholdStationDataUnit"
                   )
        elif data_type == "basin":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, BasinDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type BasinDataUnit"
                    )
        elif data_type == "basin-rainfall":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, RainfallBasinDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type RainfallBasinDataUnit"
                    )
        elif data_type == "forecast-basin":
            for data_unit in dataset.data_units:
                if not isinstance(data_unit, ForecastBasinDataUnit):
                    raise ValueError(
                        f"Data unit {data_unit} is not of type ForecastBasinDataUnit"
                    )
                
        client_ = cosmos_client.CosmosClient(
            self.secrets.get_secret("COSMOS_URL"),
            {"masterKey": self.secrets.get_secret("COSMOS_KEY")},
            user_agent="sml-api",
            user_agent_overwrite=True,
        )
        cosmos_db = client_.get_database_client("flash-flood-pipeline")
        cosmos_container_client = cosmos_db.get_container_client(data_type)
        if replace_country:
            query = get_cosmos_query(country=dataset.country)
            old_records = cosmos_container_client.query_items(query)
            for old_record in old_records:
                cosmos_container_client.delete_item(
                    item=old_record.get("id"), partition_key=dataset.country
                )
        for data_unit in dataset.data_units:
            record = vars(data_unit)
            record["timestamp"] = dataset.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
            record["country"] = dataset.country
            record["id"] = get_data_unit_id(data_unit, dataset)
            cosmos_container_client.upsert_item(body=record)

    def get_pipeline_data(
        self,
        data_type,
        country,
        start_date=None,
        end_date=None,
        adm_level=None,
        pcode=None,
        lead_time=None,
        hybasid=None,
    ) -> AdminDataSet:
        """Download pipeline datasets from Cosmos DB"""
        if data_type not in COSMOS_DATA_TYPES:
            raise ValueError(
                f"Data type {data_type} is not supported."
                f"Supported storages are {', '.join(COSMOS_DATA_TYPES)}"
            )
        client_ = cosmos_client.CosmosClient(
            self.secrets.get_secret("COSMOS_URL"),
            {"masterKey": self.secrets.get_secret("COSMOS_KEY")},
            user_agent="ibf-flood-pipeline",
            user_agent_overwrite=True,
        )
        cosmos_db = client_.get_database_client("flash-flood-pipeline")
        cosmos_container_client = cosmos_db.get_container_client(data_type)
        query = get_cosmos_query(
            start_date, end_date, country, adm_level, pcode, lead_time,hybasid
        )
        records_query = cosmos_container_client.query_items(
            query=query,
            enable_cross_partition_query=(
                True if country is None else None
            ),  # country must be the partition key
        )
        records = []
        for record in records_query:
            records.append(copy.deepcopy(record))
        datasets = []
        countries = list(set([record["country"] for record in records]))
        timestamps = list(set([record["timestamp"] for record in records]))
        for country in countries:
            for timestamp in timestamps:
                data_units = []
                for record in records:
                    if (
                        record["country"] == country
                        and record["timestamp"] == timestamp
                    ):
                        if data_type == "discharge":
                            data_unit = DischargeDataUnit(
                                adm_level=record["adm_level"],
                                pcode=record["pcode"],
                                lead_time=record["lead_time"],
                                discharge_mean=record["discharge_mean"],
                                discharge_ensemble=record["discharge_ensemble"],
                            )
                        elif data_type == "basin":
                            data_unit = BasinDataUnit(
                                pcodes=record["pcodes"],
                                hybalevel=record["hybalevel"],
                                hybasid=record["hybasid"],
                            )
                        elif data_type == "basin-rainfall":
                            data_unit = RainfallBasinDataUnit(
                                hybalevel=record["hybalevel"],
                                hybasid=record["hybasid"],
                                lead_time=record["lead_time"],
                                rainfall_mean=record["rainfall_mean"],
                                rainfall_ensemble=record["rainfall_ensemble"],
                            )
                        elif data_type == "forecast":
                            data_unit = ForecastDataUnit(
                                adm_level=record["adm_level"],
                                pcode=record["pcode"],
                                lead_time=record["lead_time"],
                                forecasts=record["forecasts"],
                                pop_affected=record["pop_affected"],
                                pop_affected_perc=record["pop_affected_perc"],
                                triggered=record["triggered"],
                                return_period=record["return_period"],
                                alert_class=record["alert_class"],
                            )
                        elif data_type == "threshold":
                            data_unit = ThresholdDataUnit(
                                adm_level=record["adm_level"],
                                pcode=record["pcode"],
                                thresholds=record["thresholds"],
                                lead_time=record["lead_time"],
                            )
                        elif data_type == "threshold-basin":
                            data_unit = ThresholdBasinDataUnit(
                                hybalevel=record["hybalevel"],
                                hybasid=record["hybasid"],
                                thresholds=record["thresholds"],
                                pcodes=record["pcodes"],
                                lead_time=record["lead_time"],
                            )
                        elif data_type == "forecast-basin":
                            data_unit = ForecastBasinDataUnit(
                                hybalevel=record["hybalevel"],
                                hybasid=record["hybasid"],
                                lead_time=record["lead_time"],
                                forecasts=record["forecasts"],
                                triggered=record["triggered"],
                                return_period=record["return_period"],
                                alert_class=record["alert_class"],
                            )
                        elif data_type == "discharge-station":
                            data_unit = DischargeStationDataUnit(
                                station_code=record["station_code"],
                                station_name=record["station_name"],
                                lat=record["lat"],
                                lon=record["lon"],
                                pcodes=record["pcodes"],
                                lead_time=record["lead_time"],
                                discharge_mean=record["discharge_mean"],
                                discharge_ensemble=record["discharge_ensemble"],
                            )
                        elif data_type == "forecast-station":
                            data_unit = ForecastStationDataUnit(
                                station_code=record["station_code"],
                                station_name=record["station_name"],
                                lat=record["lat"],
                                lon=record["lon"],
                                pcodes=record["pcodes"],
                                lead_time=record["lead_time"],
                                forecasts=record["forecasts"],
                                triggered=record["triggered"],
                                return_period=record["return_period"],
                                alert_class=record["alert_class"],
                            )
                        elif data_type == "threshold-station":
                            data_unit = ThresholdStationDataUnit(
                                station_code=record["station_code"],
                                station_name=record["station_name"],
                                lat=record["lat"],
                                lon=record["lon"],
                                pcodes=record["pcodes"],
                                thresholds=record["thresholds"],
                            )
                        else:
                            raise ValueError(f"Invalid data type {data_type}")
                        data_units.append(data_unit)
                if (
                    data_type == "discharge"
                    or data_type == "forecast"
                    or data_type == "threshold"
                ):
                    adm_levels = list(
                        set([data_unit.adm_level for data_unit in data_units])
                    )
                    dataset = AdminDataSet(
                        country=country,
                        timestamp=timestamp,
                        adm_levels=adm_levels,
                        data_units=data_units,
                    )
                    datasets.append(dataset)
                elif (
                    data_type == "basin" 
                    or data_type == "basin-rainfall"
                    or data_type == "forecast-basin"
                    or data_type == "threshold-basin"
                    ):

                    dataset = BasinDataSet(
                        country=country,
                        timestamp=timestamp,
                        data_units=data_units,
                    )
                    datasets.append(dataset)
                else:
                    dataset = StationDataSet(
                        country=country,
                        timestamp=timestamp,
                        data_units=data_units,
                    )
                    datasets.append(dataset)
        if len(datasets) == 0:
            raise KeyError(
                f"No datasets of type '{data_type}' found for country {country} in date range "
                f"{start_date} - {end_date}."
            )
        elif len(datasets) > 1:
            logging.warning(
                f"Multiple datasets of type '{data_type}' found for country {country} in date range "
                f"{start_date} - {end_date}; returning the latest (timestamp {datasets[-1].timestamp}). "
            )
        return datasets[-1]

    def __get_blob_service_client(self, blob_path: str):
        """Get service client for Azure Blob Storage"""
        blob_service_client = BlobServiceClient.from_connection_string(
            f"DefaultEndpointsProtocol=https;"
            f'AccountName={self.secrets.get_secret("BLOB_ACCOUNT_NAME")};'
            f'AccountKey={self.secrets.get_secret("BLOB_ACCOUNT_KEY")};'
            f"EndpointSuffix=core.windows.net"
        )
        container = self.settings.get_setting("blob_container")
        return blob_service_client.get_blob_client(container=container, blob=blob_path)

    def save_to_blob(self, local_path: str, file_dir_blob: str):
        """Save file to Azure Blob Storage"""
        # upload to Azure Blob Storage
        blob_client = self.__get_blob_service_client(file_dir_blob)
        with open(local_path, "rb") as upload_file:
            blob_client.upload_blob(upload_file, overwrite=True)

    def get_from_blob(self, local_path: str, blob_path: str):
        """Get file from Azure Blob Storage"""
        blob_client = self.__get_blob_service_client(blob_path)

        with open(local_path, "wb") as download_file:
            try:
                download_file.write(blob_client.download_blob().readall())
            except ResourceNotFoundError:
                raise FileNotFoundError(
                    f"File {blob_path} not found in Azure Blob Storage"
                )
