# Approved city image staging directory

This directory is the default local staging location for the controlled city-image importer.

Do not commit third-party image binaries here unless RentCrib has confirmed that the licence permits redistribution in the source repository. In normal operations, approved image files can be mounted/copied into this directory on the deployment worker or another private operations environment and referenced by `propertylist_app/data/city_image_manifest.csv`.

The importer never downloads remote URLs and never hotlinks third-party images. The manifest records source/licence metadata; the approved binary is copied into Django-managed media storage (R2 when `USE_S3=true`, otherwise the configured local media storage).
