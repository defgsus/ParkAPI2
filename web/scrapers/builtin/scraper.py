import json
import datetime
from pathlib import Path
import argparse
import glob
import importlib
import sys
import inspect
from typing import Union, Optional, Tuple, List, Type, Dict

from util import ScraperBase, LotInfo

MODULE_DIR: Path = Path(__file__).resolve().parent


def parse_args() -> dict:

    def cache_type(a) -> Union[bool, str]:
        if isinstance(a, str):
            a = a.lower()
        if a == "true":
            return True
        elif a == "false":
            return False
        elif a in ("read", "write"):
            return a
        raise ValueError  # argparse does not display the exception message

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "command", type=str,
        choices=["list", "scrape", "show-geojson", "write-geojson"],
        help="The command to execute",
    )
    parser.add_argument(
        "-p", "--pools", nargs="+", type=str,
        help=f"Filter for one or more pool IDs"
    )
    parser.add_argument(
        "-c", "--cache", nargs="?", type=cache_type, default=False, const=True,
        help=f"Enable caching of the web-requests. Specify '-c' to enable writing and reading cache"
             f", '-c read' to only read cached files or '-c write' to only write cache files"
             f" but not read them. Cache directory is {ScraperBase.CACHE_DIR}"
    )

    return vars(parser.parse_args())


def log(*args, **kwargs):
    print(datetime.datetime.now(), *args, **kwargs, file=sys.stderr)


class SnapshotMaker:

    def __init__(self, scraper: ScraperBase):
        self.scraper = scraper

    def info_map_to_geojson(self, include_unknown: bool = False) -> dict:
        info_map = self.scraper.get_lot_info_map(required=not include_unknown)

        if include_unknown:
            for lot in self.scraper.get_lot_data():
                if lot.id not in info_map:
                    # create a minimal lot info
                    info_map[lot.id] = LotInfo(
                        id=lot.id, name=lot.id, type=LotInfo.Types.lot,
                    )

        ret_data = {
            "type": "FeatureCollection",
            "features": []
        }
        for info in info_map.values():
            info = vars(info).copy()
            lat, lon = info.pop("latitude", None), info.pop("longitude", None)
            feature = {
                "type": "Feature",
                "properties": info,
            }
            if not (lat is None or lon is None):
                feature["geometry"] = {
                    "type": "Point",
                    "coordinates": [lon, lat]
                }
            ret_data["features"].append(feature)
        return ret_data

    def get_snapshot(self, required_infos: bool = True) -> dict:
        snapshot = {
            "pool": vars(self.scraper.POOL),
            "lots": [],
        }
        info_map = self.scraper.get_lot_info_map(required=True)

        for lot_data in self.scraper.get_lot_data():
            if lot_data.id in info_map:
                merged_lot = vars(info_map[lot_data.id])
            else:
                if required_infos:
                    raise ValueError(
                        f"Lot {lot_data.id} is not in lot_infos"
                    )
                merged_lot = dict()

            for key, value in vars(lot_data).items():
                if key not in merged_lot or value is not None:
                    merged_lot[key] = value

            for key, value in merged_lot.items():
                if isinstance(value, datetime.datetime):
                    merged_lot[key] = value.isoformat()

            snapshot["lots"].append(merged_lot)

        return snapshot


def get_scrapers(
        pool_filter: List[str],
) -> Dict[str, Type["ScraperBase"]]:

    scrapers = dict()
    for filename in glob.glob(str(MODULE_DIR / "*.py")):
        module_name = Path(filename).name[:-3]
        if module_name == "scraper":
            continue

        module = importlib.import_module(module_name)
        for key, value in vars(module).items():
            if not inspect.isclass(value) or not getattr(value, "POOL", None):
                continue

            if value.POOL.id in scrapers:
                raise ValueError(
                    f"class {value.__name__}.POOL.id '{value.POOL.id}'"
                    f" is already used by class {scrapers[value.POOL.id].__name__}"
                )

            if pool_filter and value.POOL.id not in pool_filter:
                continue

            scrapers[value.POOL.id] = value

    return scrapers


def main(
        command: str,
        cache: Union[bool, str],
        pools: List[str],
):
    scrapers = get_scrapers(pool_filter=pools)
    pool_ids = sorted(scrapers)

    if command == "list":
        if not pool_ids:
            print("No scrapers found")
            return

        max_length = max(len(i) for i in pool_ids)
        for pool_id in pool_ids:
            print(f"{pool_id:{max_length}}: class {scrapers[pool_id].__name__}")

    elif command == "scrape":

        print("[")
        for pool_id in pool_ids:
            log(f"scraping pool '{pool_id}'")
            scraper = scrapers[pool_id](caching=cache)
            snapshot = SnapshotMaker(scraper)
            data = snapshot.get_snapshot()
            comma = "," if pool_id != pool_ids[-1] else ""
            print(json.dumps(data, indent=2, ensure_ascii=False) + comma)
        print("]")

    elif command in ("show-geojson", "write-geojson"):

        for pool_id in pool_ids:
            log(f"scraping pool '{pool_id}'")
            scraper = scrapers[pool_id](caching=cache)
            snapshot = SnapshotMaker(scraper)
            data = snapshot.info_map_to_geojson(include_unknown=True)
            if command == "write-geojson":
                filename = Path(inspect.getfile(scraper.__class__)[:-3] + ".geojson")
                log("writing", filename)
                filename.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(**parse_args())
