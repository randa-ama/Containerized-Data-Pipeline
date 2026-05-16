# DS5220 Cloud Computing - Data Project 2: Weather Data Pipeline

## Contents of the Repository
- `weather` folder: contains core source code and environment configuration details
  - `app.py`: main application script detailing the data ingestion from the OpenMateo API, processing, and process t0 output to S3 and DynamoDB
  - `Dockerfile`: defines the process of the Docker container construction
  - `requirements.txt`: manages the required Python packages needed for the environment
- `weather-job.yaml`: defines the structure of the Kubernetes CronJob, including the execution interval, reference for the container image, and environment variables

## Data Source Summary
This application tracks real-time atmospheric data for the Central VA region using the Open-Meteo API, which is a free, open source weather API that receives its data from national weather services across the globe linked here: [OpenMateoAPI](https://open-meteo.com/en/docs). The endpoint used for fetching the current weather data was v1/forecast. The API has over 100 possible weather condition variables to pull from that are updated at various frequencies, depending on the reporting weather service, but the relevant one (United States' NOAA) is updated hourly. The data can be ingested as an instantaneous (current) reading or as a prorated or aggregated reading (15 minute, hourly, or daily) depending on the variable. The variables ingested for this pipeline were instantaneous readings.

## Application Process & Scheduling
The process I am scheduling in this project is the ingesting, augmentation, and plotting of the temperature data from the OpenMateoAPI.

This entire process was conducted utilizing AWS services. The services used were S3, EC2, and DynamoDB. The pipeline ran on a m7i-flex.large Ubuntu24.04 LTS EC2 instance within a Kubernetes cluster.

The data was ingested using a Kubernetes CronJob, which was scheduled to run every 15 minutes. At this interval, a new pod would be created, connect to the API service, retrieve the data, calculate the relevant variables, create the outputs, upload them to DynamoDB and S3, and then shut down. The app detailing the processes the CronJob would run was detailed using Python. The Kuberneted sytem ensured that if a fetch failed, it would be retried 10 times before moving on to another pod.

## Output Data & Persistence

The output dataset, named data.csv, contains 5 variables:
- `region_id`: the ID of the region the weather data is coming from
  - all Central VA based on latitude 38.03 and longitude -78.50 
- `timestamp`: the exact timestamp from when the reading was retrived from the API in UTC time
- `wind_speed`: wind speed measured at 10 meters above ground in km/h
- `temp_celsius`: the temperature measured in Celsius as ingested directly from the API
- `temp_fahrenheit`: the temperature transformed to Fahrenheit using the `temp_celsius` variable

Every reading is also stored in an Amazon DynamoDB table, named dp-tracking. The partition key is region_id, representing the area the reading is coming from. The sort key is timestamp, and the table is sorted in ascending order.

The output plot, named plot.png, is a time series graph, showing the values of temperature in Fahrenheit over time from the earliest data ingestion to the most recent. The plot is created using the Python libraries matplotlib, pandas, and seaborn.


Visualization (Plot): The application includes a Python-based processing script that uses Matplotlib or Seaborn to generate a time-series plot (e.g., weather_trend.png). This plot visualizes temperature fluctuations over the last 24–48 hours to identify local weather patterns.
