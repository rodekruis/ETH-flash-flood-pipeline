
# IBF-flash-flood-pipeline

A workflow to update flash flood forecasting portal. Part of [IBF-system](https://github.com/rodekruis/IBF-system).

## 🌊 Flash Flood Forecast Pipeline

A modular, CLI-enabled pipeline for updating flash flood forecasting portal. It fetches hydrometeorological data, processes it through deterministic and probabilistic models, evaluates risk, and pushes alerts and impact estimates to the IBF system.

This pipeline was developed to support humanitarian early action by enabling country-specific, flexible, and automated workflows.
---

## Running the flash flood Pipeline with Docker Compose

### Option 1: With Poetry
Dependency python>=3.11,<3.12
1. Fill in the secrets in .env.example and rename the file to .env; in this way, they will be loaded as environment variables. Consider using only secrets of your __test__ environment for non-production purpose.
2. Install requirements
   ```
   pip install poetry
   poetry install --no-interaction
   ```
3. Run the pipeline : `python flood_pipeline.py` or `poetry run python flood_pipeline.py` with relevant arguments below.
   ```
   Usage: flood_pipeline.py [OPTIONS]

   Options:
     --country TEXT        country ISO3
     --prepare             prepare data
     --extract             extract data
     --forecast            forecast 
     --send                send to IBF
     --save                save to storage
     --datetimestart       year-month in ISO 8601
	 --datetimeend
     --debug               debug mode: process data with mock scenario threshold
   ```
   To do a full run for a country, replace `--country TEXT` with its country ISO3 (e.g. `--country ETH`): 
   
   ```
   poetry run python flood_pipeline.py --country TEXT --prepare --extract --forecast --send --save
   ```
### Option 2: With Docker Compose

To run the flash food pipeline for testing using Docker Compose, follow these steps:

1. Ensure you have Docker and Docker Compose installed on your machine.

2. Place your `.env` file in the same directory as your `docker-compose.yml` file. This file should contain the necessary environment variables for the pipeline. The variables are in `.en.example` file 

3. Build and run the Docker container using Docker Compose:

    ```sh
    docker-compose up --build
    ```

This will build the Docker image and run the flash flood pipeline with the specified options (`--country ETH --prepare --extract --forecast --send`).

You can modify the `command` section in the `docker-compose.yml` file to change the options as needed for your testing.

---

### 🔧 Command-Line Options

| Option         | Description                                                             | Example                                    |
|----------------|-------------------------------------------------------------------------|--------------------------------------------|
| `--country`    | ISO3 code for the target country                                         | `--country ETH`                             |
| `--prepare`    | Download and prepare input data (admin boundaries, shapefiles, etc.)     | `--prepare`                                 |
| `--extract`    | Download and process forecast data (e.g., rainfall, discharge)           | `--extract`                                 |
| `--forecast`   | Run flood forecasting logic (triggers, alerts, affected population)      | `--forecast`                                |
| `--send`       | Push outputs to the IBF system API                                       | `--send`                                    |
| `--save`       | Save results to Azure Cosmos DB and Blob Storage                         | `--save`                                    |
| `--datetimestart` | Custom start date in ISO 8601 format (default: today)                | `--datetimestart 2025-06-15T00:00:00`       |
| `--datetimeend`   | Custom end date in ISO 8601 format (default: tomorrow)               | `--datetimeend 2025-06-16T00:00:00`         |
| `--debug`      | Enable debug mode (e.g., process only one ensemble, use mock data)       | `--debug`                                   |

---


## Triggering Model Run for Drought Scenarios

---

## 📦 Project Structure

The main module defines:

* 🌍 **Administrative, Station, and Basin Units** – for spatial representation of data
* 💧 **Discharge and Rainfall Units** – to manage hydrometeorological inputs
* 🚨 **Forecast and Threshold Units** – to evaluate hazard and trigger alerts
* 🧹 **Dataset Managers** – to organize and manipulate data collections across units

---
## 🧠 Key Classes

| Class                                            | Description                                                                |
| ------------------------------------------------ | -------------------------------------------------------------------------- |
| `AdminDataUnit`                                  | Represents a spatial unit (e.g. district) with admin code and level        |
| `StationDataUnit`                                | Represents a station location with coordinates and associated admin pcodes |
| `BasinDataUnit`                                  | Represents a hydrological basin with unique `hybasid`                      |
| `DischargeDataUnit`                              | Holds river discharge ensemble and computes mean                           |
| `RainfallBasinDataUnit`                          | Stores rainfall forecasts by basin                                         |
| `ForecastDataUnit`                               | Holds flood forecast data, alert level, and impact estimation              |
| `ThresholdDataUnit`                              | Stores alert thresholds by return period                                   |
| `AdminDataSet`, `StationDataSet`, `BasinDataSet` | Manage grouped data units by type and geography                            |
| `PipelineDataSets`                               | Container for all datasets needed in the flood forecasting pipeline        |


---

## 🧩 Pipeline Modules

The CLI wraps around a modular Python library composed of:

- **`pipeline.py`** – Main orchestrator of all phases
- **`extract.py`** – Downloads and processes rainfall & discharge data
- **`forecast.py`** – Computes triggers, alerts, flood extents, and impact
- **`load.py`** – Interfaces with Azure Blob, Cosmos DB, and the IBF API
- **`data/`** – Structured models for managing spatial and temporal datasets
- **`settings.py` & `secrets.py`** – Environment-aware configuration management

---

## 🧠 What It Does

✔️ **Prepares** country-specific boundaries and geospatial overlays  
✔️ **Download and Extracts** rainfall/discharge forecasts from HKV and Deltares  rainfall/flood model
✔️ **Computes** flood risk and triggers via return-period logic  
✔️ **Generates** flood extent maps and exposed population stats  
✔️ **Saves** results to cloud storage (Blob + CosmosDB)  
✔️ **Pushes** forecasts to the IBF system for anticipatory action  

---

 
 

### Requirements



## 🔐 Environment Variables

Create a `.env` file for secrets:

```dotenv
# .env
COSMOS_URL="..."
COSMOS_KEY="..."
BLOB_ACCOUNT_NAME="..."
BLOB_ACCOUNT_KEY="..."

IBF_API_URL="..."
IBF_API_USER="..."
IBF_API_PASSWORD="..."

DELTARES_FTP_URL="..."
DELTARES_FTP_USER="..."
DELTARES_FTP_PASSWORD="..."

GLOSSIS_FTP="..."
GLOSSIS_USER="..."
GLOSSIS_PW="..."
```

---

## 📜 Configuration

Each country must have a config file in YAML format:

```yaml
# config/config.yaml
ETH:
  trigger-on-return-period: 10
  trigger-on-lead-time: 3
  classify-alert-on: return-period
  alert-on-return-period:
    red: 50
    orange: 20
    yellow: 10
  alert-on-minimum-probability: 0.6
```

---

## 📝 License

MIT License



---

## 🛠️ Roadmap

- [ ] Add unit and integration tests
- [ ] Add automatic country config validation
- [ ] Deploy via Docker


---

