# Free Australian APIs — Comprehensive Reference

A categorized catalogue of free (or freemium) APIs and data feeds that provide access to Australian data. Each entry includes what data is available, how to access it, and any limitations.

---

## 1. Government Open Data Platforms

### data.gov.au
**What it provides:** Central aggregation point for Australian open government data — over 30,000 datasets from federal, state, and local government agencies covering everything from demographics to infrastructure.
**Access:** Open, no authentication required. Datasets available as CSV, JSON, and via CKAN API. Licensed under CC BY 3.0.
**URL:** https://data.gov.au

### api.gov.au
**What it provides:** A catalogue and gateway for Australian Government APIs across agencies. Includes links to APIs from ABS, IP Australia, DTA, and more.
**Access:** No key needed to browse the catalogue. Individual APIs may have their own auth requirements.
**URL:** https://api.gov.au

### api.nsw.gov.au
**What it provides:** NSW state government API gateway. Includes fuel prices, planning data, property valuations, spatial services, and more.
**Access:** Free registration required to get an API key for most endpoints.
**URL:** https://api.nsw.gov.au

### Victorian Government API Catalogue (DeveloperVic)
**What it provides:** Directory of publicly accessible Victorian Government APIs — environment monitoring, public transport, spatial data, and more.
**Access:** Free registration for API keys where required. Data licensed under Creative Commons.
**URL:** https://www.developer.vic.gov.au/api-catalogue

### Queensland Open Data Portal
**What it provides:** Datasets and APIs from Queensland Government agencies — transport, environment, health, education, and more.
**Access:** Open access, no registration for most datasets.
**URL:** https://www.data.qld.gov.au

### ACT Open Data Portal
**What it provides:** Datasets from ACT Government including air quality, transport, planning, and community services.
**Access:** Open access, no registration required.
**URL:** https://www.data.act.gov.au

### South Australia Open Data Portal
**What it provides:** SA Government datasets including crime statistics, environment, transport, and health data.
**Access:** Open access, CKAN API available.
**URL:** https://data.sa.gov.au

---

## 2. Statistics & Economic Data

### Australian Bureau of Statistics (ABS) — Data API
**What it provides:** The full range of ABS statistical datasets — Census data, labour force, CPI, trade, population, national accounts, and more. SDMX 2.1 compliant.
**Data formats:** JSON, XML, CSV.
**Access:** Completely free, no API key required.
**URL:** https://data.api.abs.gov.au/rest/data/
**Docs:** https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide

### ABS Indicator API
**What it provides:** Headline economic statistics (CPI, GDP, unemployment rate, trade balance) in a simpler format than the full Data API.
**Access:** Free, but requires an API key (register on the ABS website).
**URL:** https://api.data.abs.gov.au/

### Reserve Bank of Australia (RBA) — Statistical Tables
**What it provides:** Interest rates (cash rate, lending rates), exchange rates (AUD vs 20+ currencies), money & credit aggregates, household finances, inflation expectations, and more.
**Access:** Free CSV and XLS downloads from the RBA website. No formal API, but structured URLs make programmatic access straightforward. Third-party wrappers exist (readrba for R, exchangeratesapi.com.au for REST).
**URL:** https://www.rba.gov.au/statistics/tables/

### exchangeratesapi.com.au (Third-Party)
**What it provides:** REST API wrapping RBA exchange rate data. Current and historical AUD exchange rates.
**Access:** Free plan — 300 API calls/month plus 3 currency conversions/hour. No key needed for basic access.
**URL:** https://www.exchangeratesapi.com.au

---

## 3. Weather & Climate

### Bureau of Meteorology (BOM) — Anonymous FTP / Web Feeds
**What it provides:** Real-time forecast, warning, and observation products including radar imagery, satellite imagery, synoptic observations, and forecast districts. The most comprehensive free weather data source for Australia.
**Access:** Free, no registration. Products available via FTP (ftp.bom.gov.au) and structured web URLs. Not officially an "API" but machine-readable. Not for commercial use without agreement.
**URL:** http://www.bom.gov.au/catalogue/data-feeds.shtml

### BOM — Space Weather API
**What it provides:** Near real-time data from the Australian Space Weather Forecasting Centre — solar wind, geomagnetic indices, ionospheric data, and space weather alerts.
**Access:** Free registration required to get an API key.
**URL:** https://sws-data.sws.bom.gov.au/

### BOM — Water Data Online (SOS2 Web Services)
**What it provides:** Hydrological data from ~5,000 measurement stations across Australia — river levels, streamflow discharge, storage levels, water temperature, rainfall, groundwater levels, and more. Historical and current data.
**Access:** Free, no registration. SOS2 (Sensor Observation Service) web API.
**URL:** http://www.bom.gov.au/waterdata/
**Note:** Does not include near-real-time flood data.

### Open-Meteo — BOM ACCESS-G Model API
**What it provides:** Weather forecasts for Australia using the BOM ACCESS-G model — temperature, precipitation, wind, humidity, cloud cover, and more. Forecasts up to 10 days. Also offers a Marine Weather API and Air Quality API with Australian data.
**Access:** Free for non-commercial use, no API key needed. Commercial use requires a subscription.
**URL:** https://open-meteo.com/en/docs/bom-api

---

## 4. Energy & Electricity

### AEMO — NEM Summary JSON Endpoint
**What it provides:** Live 5-minute settlement data for the National Electricity Market — dispatch price, scheduled demand, generation, and interconnector flows by NEM region (NSW, VIC, QLD, SA, TAS).
**Access:** Free, no authentication. Public JSON endpoint.
**URL:** https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY

### AEMO — NEMWEB
**What it provides:** Comprehensive, disaggregated NEM data — dispatch, pre-dispatch, trading, bidding, constraints, FCAS, and more. Files published as CSVs in ZIP archives, updated every 5 minutes.
**Access:** Free, no registration. HTTP file server.
**URL:** https://www.nemweb.com.au/

### AEMO — Aggregated Price and Demand Data
**What it provides:** Historical aggregated price and demand data for the NEM from 1998 to present — monthly CSV files with region, timestamp, total demand, and regional reference price.
**Access:** Free download, no registration.
**URL:** https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/aggregated-data

### AEMO — Developer Portal
**What it provides:** More structured API access to AEMO data including gas and electricity markets.
**Access:** Registration required. Some APIs restricted to market participants; public APIs also available.
**URL:** https://dev.aemo.com.au/

---

## 5. Transport & Transit

### Transport for NSW — Open Data Hub
**What it provides:** Real-time and static data for all NSW public transport — buses, trains, ferries, light rail. Includes GTFS Schedule, GTFS-Realtime (vehicle positions, trip updates, alerts), timetables, and stop/route information. Update frequency: 10 seconds for buses and Sydney Trains, 30 seconds for NSW Trains.
**Access:** Free registration required. Bronze plan gives 60,000 API calls/day at 5 requests/second.
**URL:** https://opendata.transport.nsw.gov.au/

### Public Transport Victoria (PTV) — Timetable API v3
**What it provides:** Dynamic timetable data for all metropolitan and regional train, tram, and bus services in Victoria, including real-time positions. Also provides disruption information and stop data.
**Access:** Free registration required. Rate limit: 24 calls per 60 seconds per mode. Licensed CC BY 4.0.
**URL:** https://www.ptv.vic.gov.au/footer/data-and-reporting/datasets/ptv-timetable-api/
**GTFS data also at:** https://opendata.transport.vic.gov.au/

### TransLink Queensland — GTFS & GTFS-RT
**What it provides:** Static timetables and real-time feeds (GTFS-RT) for bus, train, ferry, and tram services across South East Queensland and regional bus services.
**Access:** Free. Join the TransLink Australia Google Group for data access. Data available via Queensland Open Data Portal.
**URL:** https://translink.com.au/about-translink/open-data

### Adelaide Metro — GTFS & SIRI Feeds
**What it provides:** Static GTFS and real-time SIRI feeds for Adelaide bus, train, and tram services.
**Access:** Free. Join the Adelaide Metro Developer Group for access. Licensed under Creative Commons.
**URL:** https://www.adelaidemetro.com.au/developer-info

### Transport Canberra — GTFS
**What it provides:** Static and real-time GTFS data for ACT public transport (buses and light rail).
**Access:** Free API access.
**URL:** https://www.transport.act.gov.au/ (GTFS data via ACT Open Data)

### Airservices Australia — Data Portal
**What it provides:** Australian aeronautical data — aviation facilities, airspace features, obstacles, navigation procedures, and air traffic data.
**Access:** Free registration. Some datasets are open, others require licensing agreements.
**URL:** https://data.airservicesaustralia.com/

### OpenSky Network — ADS-B API
**What it provides:** Global real-time aircraft positions via ADS-B receivers. Covers flights over Australia (coverage depends on receiver density). Includes position, altitude, velocity, and callsign.
**Access:** Free for academic/research/non-commercial use. Basic queries (all aircraft states) require no authentication. Authenticated users get higher rate limits. Register at opensky-network.org.
**URL:** https://opensky-network.org/data/api

---

## 6. Emergency Services & Hazards

### NSW Rural Fire Service — RSS/GeoJSON Feeds
**What it provides:** Current bushfire incidents across NSW with location coordinates, fire status, and alert levels. Also provides warning areas as polygons.
**Access:** Free, no registration. RSS and GeoJSON feeds.
**URL:** https://www.rfs.nsw.gov.au/news-and-media/stay-up-to-date/feeds

### Emergency WA (DFES) — RSS / CAP-AU Feeds
**What it provides:** Current emergency alerts and warnings for Western Australia — bushfires, floods, storms, and more. Includes Fire Danger Ratings and Total Fire Bans.
**Access:** Free RSS and CAP-AU format feeds, no registration.
**URL:** https://www.emergency.wa.gov.au/

### ACT Emergency Services Agency — GeoRSS
**What it provides:** Current incidents from the ACT Computer Aided Dispatch system, updated every 60 seconds.
**Access:** Free GeoRSS feed, no registration.
**URL:** https://esa.act.gov.au/

### Alert SA
**What it provides:** Real-time incident and warning information for South Australia — bushfires, floods, severe weather.
**Access:** Free web-based access and feeds.
**URL:** https://www.alert.sa.gov.au/

### SecureNT (Northern Territory)
**What it provides:** Emergency alerts and warnings from BOM, NT Fire and Rescue Service, NT Emergency Services, and Bushfires NT.
**Access:** Free, open access.
**URL:** https://securent.nt.gov.au/alerts-warnings

### Geoscience Australia — Earthquake Data
**What it provides:** Recent earthquakes (last 30 days), historical Australian earthquake catalogue, seismograms (90 days), and the National Seismic Hazard Assessment.
**Access:** Free, no registration. Web services and downloadable data.
**URL:** https://www.ga.gov.au/scientific-topics/community-safety/data-and-products

### Bushfire.io
**What it provides:** Aggregated natural disaster map for Australia combining data from state emergency services, BOM, and other sources.
**Access:** Free web access. API availability may vary.
**URL:** https://bushfire.io/

---

## 7. Air Quality & Environment

### Air Quality NSW — API
**What it provides:** Real-time and historical air quality data from the NSW monitoring network — PM2.5, PM10, ozone, NO2, SO2, CO, and meteorological variables.
**Access:** Free, no registration. Swagger UI for testing. JSON format.
**URL:** https://www.airquality.nsw.gov.au/air-quality-data-services/air-quality-api

### EPA Victoria — Environment Monitoring API
**What it provides:** Real-time environment quality data, notices, and forecasts from monitoring stations across Victoria.
**Access:** Free, available via Victorian Government Data Portal.
**URL:** https://discover.data.vic.gov.au/dataset/environment-monitoring-api

### OpenAQ
**What it provides:** Global open air quality data aggregated from government monitoring stations worldwide, including Australian stations. Provides PM2.5, PM10, O3, NO2, SO2, CO.
**Access:** Free, open API. No key required for basic access.
**URL:** https://openaq.org/

### Open-Meteo — Air Quality API
**What it provides:** Air quality forecasts including PM2.5, PM10, ozone, nitrogen dioxide, and more. Covers Australia.
**Access:** Free for non-commercial use, no key needed.
**URL:** https://open-meteo.com/en/docs/air-quality-api

---

## 8. Marine & Ocean Data

### IMOS / AODN Portal
**What it provides:** Australia's primary marine observation data repository. Includes sea surface temperature, ocean currents, wave buoy observations (height, period, direction), water temperature, salinity, chlorophyll, acoustic data, and more. Near-real-time and historical.
**Access:** Free, open access. Data available via the AODN Portal, THREDDS server, and OGC web services. No registration required for data access.
**URL:** https://portal.aodn.org.au/

### BOM — Murray-Darling Basin Water Information Portal
**What it provides:** Aggregated water data for the Murray-Darling Basin — storage levels (dams, weirs), river levels, water quality, entitlements, allocations, and trading information.
**Access:** Free, open access.
**URL:** https://mdbwip.bom.gov.au/

### Open-Meteo — Marine Weather API
**What it provides:** Wave forecasts (height, period, direction), swell data, and ocean conditions for Australian waters.
**Access:** Free for non-commercial use, no key needed.
**URL:** https://open-meteo.com/en/docs/marine-weather-api

---

## 9. Geospatial & Satellite Imagery

### NationalMap (Geoscience Australia / CSIRO)
**What it provides:** An open geospatial data viewer connecting to 13,000+ datasets from 50+ government custodians. Includes cadastral data, infrastructure, elevation, and more. Powered by TerriaJS with 3D globe visualization.
**Access:** Free, open access. Data served via OGC web services (WMS, WFS, WCS). No registration.
**URL:** https://www.nationalmap.gov.au/

### Digital Earth Australia (DEA)
**What it provides:** 35+ years of analysis-ready satellite imagery for all of Australia (Landsat from 1986, Sentinel-2). Products include land cover, water observations, fractional cover, coastline mapping, and hotspot monitoring.
**Access:** Free. Open Web Services (WMS, WMTS, WCS) and STAC API for data discovery. Data stored on AWS S3. No registration for web services.
**URL:** https://www.dea.ga.gov.au/
**STAC:** https://explorer.sandbox.dea.ga.gov.au/stac/

### Geoscience Australia — Data & Publications
**What it provides:** Geology, topography, bathymetry, geophysics (magnetics, gravity, radiometrics), groundwater, and mineral resources data for Australia.
**Access:** Free, available via web services and downloads.
**URL:** https://www.ga.gov.au/data-pubs

### ELVIS (Elevation Information System)
**What it provides:** Free LiDAR point cloud data and digital elevation models (DEMs) for areas of Australia where airborne LiDAR has been collected.
**Access:** Free, registration required for downloads.
**URL:** https://elevation.fsdf.org.au/

---

## 10. Parliamentary & Legislative Data

### OpenAustralia API
**What it provides:** Federal parliamentary data — Hansard debates, member information, divisions (votes), and representative details. Data from 2006 onwards.
**Access:** Free for low-volume, non-commercial use. API key required (register on site). Content licensed CC BY-NC-ND.
**URL:** https://www.openaustralia.org.au/api/

### NSW Parliament — Hansard API
**What it provides:** Hansard-related information for NSW Parliament — sitting dates, members, bills, and debate contents from September 1991 to present.
**Access:** Free, public API.
**URL:** https://www.parliament.nsw.gov.au/hansard/Pages/Hansard-API.aspx

### Queensland Parliament — Open Data
**What it provides:** Open datasets from the Queensland Legislative Assembly including bills, members, committees, and Hansard records.
**Access:** Free, licensed CC BY 4.0.
**URL:** https://www.parliament.qld.gov.au/Work-of-the-Assembly/Open-Data

### Australian Electoral Commission (AEC) — Election Data
**What it provides:** Federal election results at national, state, divisional, and polling-place level. Includes candidate data, vote counts, two-party preferred, and demographic breakdowns. Media Feed provides progressive results on election night.
**Access:** Free downloads (CSV) and FTP feeds. No registration needed for historical data.
**URL:** https://results.aec.gov.au/ (Tally Room Archive)

---

## 11. Finance & Markets

### Alpha Vantage (Global, includes ASX)
**What it provides:** Real-time and historical stock prices for ASX-listed companies, plus forex, crypto, and economic indicators. Intraday, daily, weekly, monthly intervals.
**Access:** Free tier — 25 API calls/day. API key required (instant registration).
**URL:** https://www.alphavantage.co/

### Yahoo Finance (Unofficial, includes ASX)
**What it provides:** Real-time and historical price data for ASX-listed stocks (use .AX suffix, e.g., BHP.AX), indices, forex, and crypto. Includes fundamentals.
**Access:** No official API, but widely used via libraries (yfinance for Python). Free, no key needed. Unofficial and may break.
**Note:** Subject to rate limiting and terms of service changes.

### Finnhub (Global, includes ASX)
**What it provides:** Real-time stock prices, company fundamentals, earnings, and news for ASX-listed companies.
**Access:** Free tier — 60 API calls/minute. API key required.
**URL:** https://finnhub.io/

### ASX.com.au (Unofficial)
**What it provides:** Current price, market announcements, and company information for ASX-listed securities via an undocumented JSON API used by the ASX website.
**Access:** No official API. Can be accessed programmatically (pyasx library) but is undocumented and unsupported. Use at own risk.
**URL:** https://www.asx.com.au/

---

## 12. Health & Welfare

### Australian Institute of Health and Welfare (AIHW) — Data Portal
**What it provides:** Comprehensive health and welfare statistics — hospital performance, disease prevalence, Medicare/PBS utilization, mental health, aged care, disability, housing, and Indigenous health data.
**Access:** Free downloads (Excel, CSV). Interactive dashboards available. No formal REST API, but structured data files.
**URL:** https://www.aihw.gov.au/

### Services Australia — Medicare & PBS Statistics
**What it provides:** Statistical information about Medicare, PBS, and other programs — service volumes, expenditure, and utilization. Published on data.gov.au in machine-readable formats.
**Access:** Free, available via data.gov.au. No registration.
**URL:** https://www.servicesaustralia.gov.au/statistical-information-and-data

---

## 13. Fuel Prices

### NSW Fuel API (FuelCheck)
**What it provides:** Live fuel prices across 2,500+ service stations in NSW (and Tasmania via v2). All fuel types — unleaded, premium, diesel, LPG, E10.
**Access:** Free registration on api.nsw.gov.au for an API key.
**URL:** https://api.nsw.gov.au/Product/Index/22

### FuelPrice Australia API (Third-Party)
**What it provides:** Real-time fuel prices from 9,700+ stations across all Australian states and territories. Current and historical pricing.
**Access:** Free tier available with limited calls. API key required.
**URL:** https://fuelprice.io/api/

---

## 14. Biodiversity & Natural Science

### Atlas of Living Australia (ALA) — API
**What it provides:** Australia's national biodiversity database — 100+ million species occurrence records across 153,000+ species. Geospatial, taxonomic, and temporal search. Includes species profiles, images, and conservation status.
**Access:** Free. Recently moved to an API Gateway with user authentication. Register for an API key.
**URL:** https://docs.ala.org.au/
**Portal:** https://www.ala.org.au/

### CSIRO — Soil and Landscape Grid of Australia (SLGA)
**What it provides:** National soil attribute maps at ~90m resolution — pH, clay content, organic carbon, bulk density, available water capacity, depth, and more.
**Access:** Free. Available via WCS/WMS web services and Google Earth Engine.
**URL:** https://www.clw.csiro.au/aclep/soilandlandscapegrid/

---

## 15. Cultural Heritage & Libraries

### National Library of Australia — Trove API
**What it provides:** Search and access to Australian cultural heritage collections — digitized newspapers (1803–present), books, images, maps, music, archives, and more from libraries, museums, and galleries nationwide. Over 600 million items.
**Access:** Free. API key required (register at Trove). Rate limits apply.
**URL:** https://trove.nla.gov.au/
**API Docs:** https://trove.nla.gov.au/about/create-something/using-api

---

## 16. Agriculture & Land Use

### ABARES — Web Mapping Services
**What it provides:** Spatial data on Australian agriculture, forestry, fisheries, and land use. Includes land use mapping, crop statistics, and commodity data.
**Access:** Free. OGC WMS/WFS web services.
**URL:** https://www.agriculture.gov.au/abares/data/web-mapping-services

### Murray-Darling Basin Flow-MER Data
**What it provides:** Ecological and hydrological monitoring data from the Murray-Darling Basin environmental water program.
**Access:** Free, published to data.gov.au under open data policy (FAIR principles).
**URL:** https://data.gov.au/ (search "Flow-MER")

---

## 17. Intellectual Property

### IP Australia — APIs
**What it provides:** Search and retrieve Australian trade mark, patent, and design data. Bulk data extracts and real-time search.
**Access:** Free. API key may be required for some endpoints.
**URL:** https://www.ipaustralia.gov.au/tools-and-research/professional-resources/apis

---

## 18. Property & Land Values

### NSW Valuer General — Bulk Land Values
**What it provides:** Bulk land value data for all NSW Local Government Areas from July 2017 onwards. Updated monthly.
**Access:** Free download (ZIP/CSV). No registration.
**URL:** https://data.nsw.gov.au/ (search "land values")

### NSW Property Web Service
**What it provides:** Spatial property data — polygon boundaries representing property descriptions from the Valuer General's Department.
**Access:** Free via api.nsw.gov.au. Registration required.
**URL:** https://api.nsw.gov.au/Product/Index/20

---

## 19. Crime Statistics

### NSW Bureau of Crime Statistics and Research (BOCSAR)
**What it provides:** Recorded crime data for NSW — quarterly reports by offence type, LGA, and time period from 1995 onwards.
**Access:** Free downloads via data.nsw.gov.au. No registration.
**URL:** https://data.nsw.gov.au/ (search "crime")

### SA Police (SAPOL) — Crime Statistics
**What it provides:** Suburb-based crime statistics — offences against person and property, 5 years of data.
**Access:** Free via data.sa.gov.au. No registration.
**URL:** https://data.sa.gov.au/data/dataset/crime-statistics

---

## 20. Miscellaneous & Third-Party Global APIs with Australian Data

### USGS Earthquake API (Global, includes Australia)
**What it provides:** Real-time and historical earthquake data worldwide, including Australian events. FDSN Event web service. Magnitude, depth, location, and time.
**Access:** Free, no registration. CORS-friendly for browser use.
**URL:** https://earthquake.usgs.gov/fdsnws/event/1/

### OpenFlights (Global Reference Data)
**What it provides:** Static reference datasets for airports (including all Australian airports), airlines, and routes. CSV format.
**Access:** Free download from GitHub. No API, static data files.
**URL:** https://openflights.org/data.php

### WillyWeather API (Australian-specific)
**What it provides:** Weather forecasts, tides, swell, UV, sunrise/sunset, and rain radar for Australian locations. Sources from BOM.
**Access:** Freemium. Free tier with limited calls, paid plans for higher volume.
**URL:** https://www.willyweather.com.au/info/api.html

### Australian Postcode / Suburb Data
**What it provides:** Postcodes, suburb names, states, and geographic coordinates for all Australian localities.
**Access:** Free via data.gov.au (search "postcodes") or various open datasets.

---

## Quick Reference: Access Requirements Summary

| Access Level | APIs |
|---|---|
| **No auth needed** | ABS Data API, AEMO NEM Summary, NEMWEB, BOM FTP/Web, USGS Earthquakes, Open-Meteo, OpenAQ, AODN Portal, NationalMap, data.gov.au, most RSS emergency feeds |
| **Free registration / API key** | Transport NSW, PTV Victoria, TransLink QLD, BOM Space Weather, ABS Indicator API, NSW Fuel API, Trove, ALA, Airservices Australia, api.nsw.gov.au services, Alpha Vantage, Finnhub |
| **Free but structured access** | RBA statistics (CSV downloads), AEC election data (CSV/FTP), AIHW dashboards, DEA (web services + STAC), crime statistics (CSV downloads) |
| **Unofficial / undocumented** | ASX.com.au JSON, Yahoo Finance, BOM weather API (beta site) |

---

*Compiled April 2026. URLs and access terms are subject to change. Always check the provider's current documentation before building production integrations.*
