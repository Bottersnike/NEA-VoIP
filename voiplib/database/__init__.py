from .orm import DB, Primary


db = DB(':memory:')


@db.object
class GateConfig:
    attack: float
    hold: float
    release: float
    threshold: float


@db.object
class CompConfig:
    attack: float
    release: float
    threshold: float


@db.object
class Devices:
    deviceID: Primary[str]
    MAC: str
    lastIp: str
    name: str
    prioritySpeaker: bool
    gate: GateConfig
    comp: CompConfig


@db.object
class Histories:
    device: Devices
    timestamp: int
    event: int
    details: str


db.prepare()
