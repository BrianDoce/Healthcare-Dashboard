# Reproduces data/raw: 5,000 Massachusetts patients, fixed seed. Needs Java 17+ and the Synthea jar.
param([string]$Java = "java", [string]$Jar = "tools\dl\synthea-with-dependencies.jar")
& $Java -jar $Jar -p 5000 -s 42 -cs 42 `
  --exporter.baseDirectory=data/synthea_out --exporter.csv.export=true `
  --exporter.fhir.export=false --exporter.hospital.fhir.export=false `
  --exporter.practitioner.fhir.export=false Massachusetts
New-Item -ItemType Directory -Force data\raw | Out-Null
Copy-Item data\synthea_out\csv\*.csv data\raw\ -Force
