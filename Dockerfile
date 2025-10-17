FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y libexpat1 
# install ODBC Driver for SQL Server
RUN deps='curl gnupg gnupg2' && \
	apt-get update && \
	apt-get install -y $deps

	# System deps + Azure CLI (bookworm)
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg lsb-release apt-transport-https \
      build-essential git wget libxml2-utils gir1.2-secret-1 \
      gdal-bin libgdal-dev libproj-dev libgeos-dev libspatialindex-dev \
      libudunits2-dev libcairo2-dev libgirepository1.0-dev gfortran \
      libeccodes0 python3-eccodes \
    && curl -sL https://packages.microsoft.com/keys/microsoft.asc \
         | gpg --dearmor -o /etc/apt/trusted.gpg.d/microsoft.asc.gpg \
    && echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ bookworm main" \
         > /etc/apt/sources.list.d/azure-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends azure-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

#RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
#	curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.#list && \
#	apt-get update && \
#	ACCEPT_EULA=Y apt-get install -y msodbcsql18
RUN pip install poetry

# clean up
RUN set -ex apt-get autoremove -y && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*

# add credentials and install drought pipeline
WORKDIR .
COPY pyproject.toml poetry.lock /
RUN poetry config virtualenvs.create false
RUN poetry install --no-root --no-interaction
COPY floodpipeline /floodpipeline
#COPY data_updates /data_updates
#COPY tests /tests
COPY config /config
# Create the target directories inside the container
RUN mkdir -p /data/input /data/output 
#COPY data /data
COPY "flood_pipeline.py" .
#COPY "run_scenario.py" .

# ENTRYPOINT ["poetry", "run", "python", "-m", "flood_pipeline"]
 
