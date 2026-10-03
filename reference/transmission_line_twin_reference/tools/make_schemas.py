import json
from pathlib import Path
from tl_twin.contracts import Measurement, LineConfig

for name, model in (("measurement.v1",Measurement),("line-config.v1",LineConfig)):
    path=Path("schemas")/(name+".json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(model.model_json_schema(),indent=2))
    print(path)
