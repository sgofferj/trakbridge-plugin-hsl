# hsl.py from https://github.com/sgofferj/trakbridge-plugin-hsl.git
#
# Copyright Stefan Gofferje
#
# Licensed under the Gnu General Public License Version 3 or higher (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at https://www.gnu.org/licenses/gpl-3.0.en.html

"""
HSL (Helsinki Regional Transport) Plugin for TrakBridge
"""

import asyncio
import fnmatch
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

import aiohttp
import paho.mqtt.client as mqtt
from plugins.base_plugin import (
    BaseGPSPlugin,
    PluginConfigField,
)
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

HSL_MQTT_BROKER = "mqtt.hsl.fi"
HSL_MQTT_PORT = 1883
HFP_TOPIC_BASE = "/hfp/v2/journey/ongoing/vp"

MODE_MAP = {
    "tram": "a-f-G-E-V-L-T",
    "metro": "a-f-G-E-V-L-R",
    "train": "a-f-G-E-V-L",
    "ferry": "a-f-S-X-C",
    "bus": "a-f-G-E-V-C-M",
}

TRIP_LOCK_SECONDS = 30
ENTRY_STALE_SECONDS = 300
LOCK_CLEANUP_INTERVAL = 60


def parse_hfp_topic(topic: str) -> Optional[Tuple[str, str]]:
    """
    Parse an HFP topic and return (mode, route_id).

    Topic layout:
    /hfp/v2/journey/ongoing/vp/<mode>/<oper>/<veh>/<route>/...
    """
    parts = topic.split("/")
    if len(parts) < 10:
        return None
    return parts[6], parts[9]


class HslPlugin(BaseGPSPlugin):  # type: ignore[misc]
    """HSL real-time vehicle tracking integration"""

    PLUGIN_NAME = "hsl"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._buffer: Dict[str, Dict[str, Any]] = {}
        self._trip_locks: Dict[str, Tuple[str, float]] = {}
        self._trip_cars: Dict[str, set[str]] = {}
        self._mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_task: Optional[asyncio.Task[None]] = None
        self._stop_mqtt = False
        self._last_cleanup = 0.0

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "HSL Plugin",
            "description": "Real-time tracking of HSL "
            "(Helsinki Regional Transport) vehicles via HFP MQTT",
            "icon": "fas fa-train-subway",
            "category": "custom",
            "min_poll_interval": 5,
            "hide_cot_type": True,
            "config_fields": [
                PluginConfigField(
                    name="hsl_route_filter",
                    label="Route Filter",
                    field_type="text",
                    required=False,
                    help_text=(
                        "Comma-separated list of route IDs or passenger route "
                        "numbers to show (e.g., 15,M1,M2,L*). Wildcards are "
                        "supported. Leave empty for all routes."
                    ),
                ),
            ],
            "help_sections": [
                {
                    "title": "Overview",
                    "content": [
                        "This plugin connects to the HSL High-Frequency "
                        "Positioning (HFP) MQTT broker and generates CoT events "
                        "for trams, subways, trains, ferries and buses.",
                        "Use the route filter to restrict output to specific "
                        "routes. Wildcards (fnmatch style) are supported.",
                    ],
                }
            ],
        }

    def _get_route_filter(self) -> str:
        config = self.get_decrypted_config()
        return cast(str, config.get("hsl_route_filter", "")).strip()

    def _matches_filter(self, r_id: str, desi: str, route_filter: str) -> bool:
        """Check if a route matches the configured filter (supports wildcards)."""
        if not route_filter:
            return True

        clean_rid = r_id.replace("HSL:", "")
        clean_desi = desi.replace("HSL:", "")
        filters = [f.strip().replace("HSL:", "") for f in route_filter.split(",")]

        for pattern in filters:
            if pattern and (
                fnmatch.fnmatch(clean_rid, pattern)
                or fnmatch.fnmatch(clean_desi, pattern)
            ):
                return True
        return False

    def _process_message(self, topic: str, payload: bytes) -> None:
        """Process a message from the HSL HFP MQTT broker."""
        parsed = parse_hfp_topic(topic)
        if not parsed:
            return
        mode, r_id = parsed

        payload_data = json.loads(payload.decode("utf-8"))
        vp = payload_data.get("VP")
        if not vp:
            return

        desi = vp.get("desi", "")
        route_filter = self._get_route_filter()
        if not self._matches_filter(r_id, desi, route_filter):
            return

        lat = vp.get("lat")
        lon = vp.get("long")
        if lat is None or lon is None:
            return

        # Stabilization: lock trip to a single car ID ("anti-jitter")
        trip_key = f"{mode}-{r_id}-{vp.get('oday')}-{vp.get('start')}-{vp.get('dir')}"
        car_id = f"{vp.get('oper')}_{vp.get('veh')}"
        now = time.time()

        if trip_key not in self._trip_cars:
            self._trip_cars[trip_key] = set()
        self._trip_cars[trip_key].add(car_id)

        if trip_key in self._trip_locks:
            locked_car, last_seen = self._trip_locks[trip_key]
            if car_id != locked_car and now - last_seen < TRIP_LOCK_SECONDS:
                return

        self._trip_locks[trip_key] = (car_id, now)

        cot_type = MODE_MAP.get(mode, "a-f-G-E-V-C-M")
        route_display = desi or r_id.replace("HSL:", "")

        remarks = (
            f"Route: {route_display}\n"
            f"Cars: {', '.join(sorted(self._trip_cars[trip_key]))}\n"
            f"Trip: {vp.get('start')}\n"
            f"Occupancy: {vp.get('occu')}\n"
            "#HSL"
        )

        self._buffer[trip_key] = {
            "uid": f"HSL-{trip_key}",
            "cot_type": cot_type,
            "lat": lat,
            "lon": lon,
            "hae": 0,
            "name": f"HSL {route_display}",
            "speed": float(vp.get("spd") or 0.0),
            "course": float(vp.get("hdg") or 0.0),
            "description": remarks,
            "last_seen": datetime.now(timezone.utc),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }

    def _cleanup_stale(self) -> None:
        now = time.time()
        self._trip_locks = {
            k: v
            for k, v in self._trip_locks.items()
            if now - v[1] < ENTRY_STALE_SECONDS
        }
        self._trip_cars = {
            k: v for k, v in self._trip_cars.items() if k in self._trip_locks
        }
        cutoff = datetime.now(timezone.utc).timestamp() - ENTRY_STALE_SECONDS
        self._buffer = {
            k: v
            for k, v in self._buffer.items()
            if v["last_seen"].timestamp() >= cutoff
        }

    async def _mqtt_loop(self) -> None:
        """Background task for MQTT."""
        route_filter = self._get_route_filter()

        def on_connect(
            client: mqtt.Client,
            _userdata: Any,
            _flags: Dict[str, Any],
            rc: int,
            _properties: Any = None,
        ) -> None:
            if rc == 0:
                logger.info(
                    f"HSL: Connected to MQTT broker at {HSL_MQTT_BROKER}:"
                    f"{HSL_MQTT_PORT}"
                )
                # If any filter has a wildcard or no filter is set, subscribe
                # to the global topic; otherwise use targeted subscriptions.
                if "*" in route_filter or not route_filter:
                    topic = f"{HFP_TOPIC_BASE}/#"
                    client.subscribe(topic)
                    logger.info(f"HSL: Subscribed to global topic: {topic}")
                else:
                    for r_id in route_filter.split(","):
                        clean_rid = r_id.strip().replace("HSL:", "")
                        topic = f"{HFP_TOPIC_BASE}/+/+/+/{clean_rid}/#"
                        client.subscribe(topic)
                        logger.info(f"HSL: Subscribed to targeted topic: {topic}")
            else:
                logger.error(f"HSL: MQTT connection failed with result code {rc}")

        def on_disconnect(
            _client: mqtt.Client,
            _userdata: Any,
            _flags: Any,
            rc: int,
            _properties: Any = None,
        ) -> None:
            logger.warning(f"HSL: Disconnected from MQTT broker, code {rc}")

        def on_message(
            _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
        ) -> None:
            try:
                self._process_message(msg.topic, msg.payload)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"HSL: Error processing MQTT message: {e}")

        self._mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
            client_id=f"trakbridge-plugin-hsl-{uuid.uuid4()}",
        )
        self._mqtt_client.on_connect = on_connect
        self._mqtt_client.on_disconnect = on_disconnect  # type: ignore[assignment]
        self._mqtt_client.on_message = on_message

        try:
            logger.info(f"HSL: Connecting to {HSL_MQTT_BROKER}:{HSL_MQTT_PORT}...")
            self._mqtt_client.connect(HSL_MQTT_BROKER, HSL_MQTT_PORT, 60)
            self._mqtt_client.loop_start()

            while not self._stop_mqtt:
                await asyncio.sleep(LOCK_CLEANUP_INTERVAL)
                self._cleanup_stale()

            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(f"HSL: MQTT loop error: {e}")

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        # session is unused but required by BasePlugin interface
        _ = session
        if self._mqtt_task is None or self._mqtt_task.done():
            self._stop_mqtt = False
            self._mqtt_task = asyncio.create_task(self._mqtt_loop())

        now = datetime.now(timezone.utc)
        locations = []
        for entry in self._buffer.values():
            age = (now - entry["last_seen"]).total_seconds()
            if age < ENTRY_STALE_SECONDS:
                locations.append(
                    {
                        "uid": entry["uid"],
                        "cot_type": entry["cot_type"],
                        "lat": entry["lat"],
                        "lon": entry["lon"],
                        "hae": entry["hae"],
                        "name": entry["name"],
                        "speed": entry["speed"],
                        "course": entry["course"],
                        "description": entry["description"],
                        "timestamp": entry["timestamp"],
                    }
                )
        return locations

    def validate_config(self) -> bool:
        return True

    async def test_connection(self) -> Dict[str, Any]:
        return {
            "success": True,
            "message": "Configuration valid. Connection is handled in background.",
        }

    def __del__(self) -> None:
        self._stop_mqtt = True
        if self._mqtt_task and not self._mqtt_task.done():
            self._mqtt_task.cancel()
