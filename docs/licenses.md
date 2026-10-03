# Dependency license record

The application uses the supplied pinned scientific stack. Installed Python
distribution license metadata/classifiers/project URLs and locked npm license
records are recorded in `evidence/dependency-licenses.json` by `tools/licenses.py`.
This file preserves the original metadata rather than guessing absent licenses.
Use distribution license files when preparing a redistributable release.

The main frontend libraries report MIT licenses (React, React DOM, React Flow,
Recharts, Vite and lucide-react) in the npm lock. Python/scientific distributions
include their own license notices and bundled third-party notices; NumPy/SciPy
wheel metadata can be long because bundled numerical libraries have additional
terms. PostgreSQL, Mosquitto, Python and Node container images retain their
upstream licensing; image license inventories were not executed here.

The supplied reference archive does not contain a project LICENSE file. Its
provenance is retained with all source files and checksums. No ownership or
redistribution license is invented for that supplied material. A project-wide
distribution license has not been selected. Local use/build/test of the supplied
project and generated application is the scope of this delivery.
