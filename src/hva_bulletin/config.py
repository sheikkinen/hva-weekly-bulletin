import json
from importlib.resources import files

from pydantic import BaseModel, HttpUrl


class HvaConfig(BaseModel):
    name: str
    adapter: str
    url: HttpUrl


def load_hvas() -> list[HvaConfig]:
    path = files("hva_bulletin").joinpath("data/hvas.json")
    return [HvaConfig.model_validate(record) for record in json.loads(path.read_text())]
