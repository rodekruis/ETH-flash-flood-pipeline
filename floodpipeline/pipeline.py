from floodpipeline.data import AdminDataSet, StationDataSet
from floodpipeline.extract import Extract
from floodpipeline.forecast import Forecast
from floodpipeline.load import Load
from floodpipeline.secrets import Secrets
from floodpipeline.settings import Settings
from floodpipeline.data import PipelineDataSets
from datetime import datetime, date, timedelta
import logging
import shutil
import os

logger = logging.getLogger()
logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)


class Pipeline:
    """Base class for flood data pipeline"""

    def __init__(self, settings: Settings, secrets: Secrets, country: str):
        self.settings = settings
        if country not in [c["name"] for c in self.settings.get_setting("countries")]:
            raise ValueError(f"No config found for country {country}")
        self.country = country
        self.load = Load(settings=settings, secrets=secrets)
        self.data = PipelineDataSets(country=country, settings=settings)
        self.output_data_path: str = "data/output"

        self.data.threshold_admin = self.load.get_pipeline_data(
            data_type="threshold", country=self.country
        )
        self.data.threshold_station = self.load.get_pipeline_data(
            data_type="threshold-station", country=self.country
        )
        self.data.threshold_basin = self.load.get_pipeline_data(
            data_type="threshold-basin", country=self.country
        )

        self.extract = Extract(
            settings=settings,
            secrets=secrets,
            data=self.data,
        )
        self.forecast = Forecast(
            settings=settings,
            secrets=secrets,
            data=self.data,
        )

    def run_pipeline(
        self,
        prepare: bool = True,
        extract: bool = True,
        forecast: bool = True,
        send: bool = True,
        save: bool = True,
        debug: bool = False,  # fast extraction on yesterday's data
        datetimestart: datetime = date.today(),
        datetimeend: datetime = date.today() + timedelta(days=1),
    ):
        """Run the flood data pipeline"""

        # Remove the folder if it exists
        if os.path.exists(self.output_data_path):
            shutil.rmtree(self.output_data_path)

        # Recreate the empty folder
        os.makedirs(self.output_data_path)


        if prepare:
            logging.info("prepare data")
            self.extract.prepare_hkvrain_data(country=self.country, debug=debug)
            self.extract.prepare_wflow_data(country=self.country, debug=debug)

        if extract:
            logging.info(f"extract data")
            self.extract.extract_hkvrain_data_nc(country=self.country, debug=debug)
            self.extract.extract_wflow_data(country=self.country, debug=debug)
            if save:
                logging.info("save data to storage")
                self.load.save_pipeline_data(
                    data_type="discharge", dataset=self.data.discharge_admin
                )
                self.load.save_pipeline_data(
                    data_type="discharge-station", dataset=self.data.discharge_station
                )
                self.load.save_pipeline_data(
                    data_type="basin-rainfall", dataset=self.data.basin_rainfall
                )
        else:
            logging.info(f"get data from storage")
            self.data.discharge_admin = self.load.get_pipeline_data(
                data_type="discharge",
                country=self.country,
                start_date=datetimestart,
                end_date=datetimeend,
            )
            self.data.discharge_station = self.load.get_pipeline_data(
                data_type="discharge-station",
                country=self.country,
                start_date=datetimestart,
                end_date=datetimeend,
            )
            self.data.basin_rainfall = self.load.get_pipeline_data(
                data_type="basin-rainfall",
                country=self.country,
                start_date=datetimestart,
                end_date=datetimeend,
            )

        if forecast:
            logging.info("forecast floods")
            self.forecast.compute_forecast()
            if save:
                logging.info("save flood forecasts to storage")
                self.load.save_pipeline_data(
                    data_type="forecast", dataset=self.data.forecast_admin
                )
                self.load.save_pipeline_data(
                    data_type="forecast-station", dataset=self.data.forecast_station
                )
                self.load.save_pipeline_data(
                    data_type="forecast-basin", dataset=self.data.basin_rainfall
                )

        if send:
            if not forecast:
                logging.info("get flood forecasts from storage")
                self.data.forecast_admin = self.load.get_pipeline_data(
                    data_type="forecast",
                    country=self.country,
                    start_date=datetimestart,
                    end_date=datetimeend,
                )
                self.data.forecast_station = self.load.get_pipeline_data(
                    data_type="forecast-station",
                    country=self.country,
                    start_date=datetimestart,
                    end_date=datetimeend,
                )
                self.data.basin_rainfall = self.load.get_pipeline_data(
                    data_type="forecast-basin",
                    country=self.country,
                    start_date=datetimestart,
                    end_date=datetimeend,
                )
            logging.info("send data to IBF API")
            self.load.send_to_ibf_api(
                forecast_data=self.data.forecast_admin,
                discharge_data=self.data.discharge_admin,
                forecast_station_data=self.data.forecast_station,
                discharge_station_data=self.data.discharge_station,
                flood_extent=self.forecast.flood_extent_raster,
            )
