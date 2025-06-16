
# IBF-flash-flood-pipeline

Forecast riverine flooding. Part of [IBF-system](https://github.com/rodekruis/IBF-system).

## 🌊 Flash Flood Forecast Pipeline

A modular, CLI-enabled pipeline for anticipatory flood forecasting. It fetches hydrometeorological data, processes it through deterministic and probabilistic models, evaluates risk, and pushes alerts and impact estimates to external platforms like the IBF system.

This pipeline was developed to support humanitarian early action by enabling country-specific, flexible, and automated workflows.

---
## 📦 Project Structure

The main module defines:

* 🌍 **Administrative, Station, and Basin Units** – for spatial representation of data
* 💧 **Discharge and Rainfall Units** – to manage hydrometeorological inputs
* 🚨 **Forecast and Threshold Units** – to evaluate hazard and trigger alerts
* 🧹 **Dataset Managers** – to organize and manipulate data collections across units

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

 

## 🚀 Quick Start

Run the pipeline directly from the command line:

```bash
python run_pipeline.py --country UGA --prepare --extract --forecast --send --save
```

---

## 🔧 Command-Line Options

| Option         | Description                                                             | Example                                    |
|----------------|-------------------------------------------------------------------------|--------------------------------------------|
| `--country`    | ISO3 code for the target country                                         | `--country KEN`                             |
| `--prepare`    | Download and prepare input data (admin boundaries, shapefiles, etc.)     | `--prepare`                                 |
| `--extract`    | Download and process forecast data (e.g., rainfall, discharge)           | `--extract`                                 |
| `--forecast`   | Run flood forecasting logic (triggers, alerts, affected population)      | `--forecast`                                |
| `--send`       | Push outputs to the IBF system API                                       | `--send`                                    |
| `--save`       | Save results to Azure Cosmos DB and Blob Storage                         | `--save`                                    |
| `--datetimestart` | Custom start date in ISO 8601 format (default: today)                | `--datetimestart 2025-06-15T00:00:00`       |
| `--datetimeend`   | Custom end date in ISO 8601 format (default: tomorrow)               | `--datetimeend 2025-06-16T00:00:00`         |
| `--debug`      | Enable debug mode (e.g., process only one ensemble, use mock data)       | `--debug`                                   |

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

## 📁 Example: Full Run

```bash
python run_pipeline.py --country ETH --prepare --extract --forecast --send --save
```

---

## 📦 Installation

### Requirements



## 🔐 Environment Variables

Create a `.env` file for secrets:

```dotenv
# .env
DELTARES_FTP_USER=your_user
DELTARES_FTP_PASSWORD=your_pass
AZURE_BLOB_KEY=...
COSMOS_DB_KEY=...
IBF_API_TOKEN=...
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

## 🧪 Developer Notes

You can run pipeline steps independently:

```bash
python run_pipeline.py --country ETH --extract
python run_pipeline.py --country ETH --forecast
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

## 👤 Author

Developed by **Tekle** as part of the ETH Flash Flood Anticipatory Action initiative.


