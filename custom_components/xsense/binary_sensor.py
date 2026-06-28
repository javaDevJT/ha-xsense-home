"""Support for xsense binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from xsense.device import Device
from xsense.entity import Entity
from xsense.entity_map import EntityType, entities
from xsense.station import Station

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import XSenseDataUpdateCoordinator
from .entity import XSenseEntity


@dataclass(kw_only=True, frozen=True)
class XSenseBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes XSense binary-sensor entity."""

    exists_fn: Callable[[Entity], bool] = lambda _: True
    value_fn: Callable[[Entity], bool]
    device_class_fn: Callable[[Entity], BinarySensorDeviceClass | None] | None = None
    icon_fn: Callable[[Entity], str | None] | None = None


ALARM_DEVICE_CLASS_BY_ENTITY_TYPE: dict[EntityType, BinarySensorDeviceClass | None] = {
    EntityType.SMOKE: BinarySensorDeviceClass.SMOKE,
    EntityType.COMBI: BinarySensorDeviceClass.SMOKE,
    EntityType.CO: BinarySensorDeviceClass.CO,
    EntityType.WATER: BinarySensorDeviceClass.MOISTURE,
    EntityType.MOTION: BinarySensorDeviceClass.MOTION,
    EntityType.HEAT: BinarySensorDeviceClass.HEAT,
    EntityType.MAILBOX: None,
}

ALARM_ICON_BY_ENTITY_TYPE: dict[EntityType, str] = {
    EntityType.MAILBOX: "mdi:mailbox-up-outline",
}


def xsense_entity_type(entity: Entity) -> EntityType | None:
    """Return the python-xsense entity type for an entity."""
    return entities.get(entity.type, {}).get("type")


def alarm_device_class(entity: Entity) -> BinarySensorDeviceClass | None:
    """Return the Home Assistant device class for an alarm status sensor."""
    return ALARM_DEVICE_CLASS_BY_ENTITY_TYPE.get(xsense_entity_type(entity))


def alarm_icon(entity: Entity) -> str | None:
    """Return a custom icon for an alarm status sensor."""
    return ALARM_ICON_BY_ENTITY_TYPE.get(xsense_entity_type(entity))


SENSORS: tuple[XSenseBinarySensorEntityDescription, ...] = (
    XSenseBinarySensorEntityDescription(
        key="is_life_end",
        translation_key="is_life_end",
        name="End of life",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:timelapse",
        exists_fn=lambda entity: "isLifeEnd" in entity.data,
        value_fn=lambda entity: entity.data["isLifeEnd"] == 1,
    ),
    XSenseBinarySensorEntityDescription(
        key="alarm_status",
        name="Alarm detected",
        device_class_fn=alarm_device_class,
        icon_fn=alarm_icon,
        exists_fn=lambda entity: "alarmStatus" in entity.data,
        value_fn=lambda entity: entity.data["alarmStatus"],
    ),
    XSenseBinarySensorEntityDescription(
        key="mute_status",
        translation_key="mute_status",
        name="Muted",
        icon="mdi:alarm-light-off",
        exists_fn=lambda entity: "muteStatus" in entity.data,
        value_fn=lambda entity: entity.data["muteStatus"],
    ),
    XSenseBinarySensorEntityDescription(
        key="activate",
        translation_key="activate",
        name="Alarm active",
        icon="mdi:bell-ring",
        exists_fn=lambda entity: "activate" in entity.data,
        value_fn=lambda entity: entity.data["activate"],
    ),
    XSenseBinarySensorEntityDescription(
        key="door",
        translation_key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        name="Door",
        value_fn=lambda device: device.data["isOpen"] == "1",
        exists_fn=lambda device: "isOpen" in device.data,
    ),
)

MQTTSensor = XSenseBinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    name="Connected",
    entity_category=EntityCategory.DIAGNOSTIC,
    icon="mdi:connection",
    exists_fn=lambda entity: isinstance(entity, Station),
    value_fn=lambda entity: False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the xsense binary sensor entry."""
    devices: list[Device] = []
    coordinator: XSenseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    for station in coordinator.data["stations"].values():
        devices.extend(
            XSenseBinarySensorEntity(coordinator, station, description)
            for description in SENSORS
            if description.exists_fn(station)
        )
        devices.append(XSenseMQTTConnectedEntity(coordinator, station, MQTTSensor))

    for dev in coordinator.data["devices"].values():
        devices.extend(
            XSenseBinarySensorEntity(
                coordinator, dev, description, station_id=dev.station.entity_id
            )
            for description in SENSORS
            if description.exists_fn(dev)
        )

    async_add_entities(devices)


class XSenseBinarySensorEntity(XSenseEntity, BinarySensorEntity):
    """Binary sensors for xsense."""

    entity_description: XSenseBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: XSenseDataUpdateCoordinator,
        entity: Entity,
        entity_description: XSenseBinarySensorEntityDescription,
        station_id: str | None = None,
    ) -> None:
        """Set up the instance."""
        self._station_id = station_id
        self.entity_description = entity_description
        self._attr_available = False  # This overrides the default

        super().__init__(coordinator, entity, station_id)

    @property
    def _xsense_entity(self) -> Entity:
        """Return the current xsense entity backing this Home Assistant entity."""
        if self._station_id:
            return self.coordinator.data["devices"][self._dev_id]
        return self.coordinator.data["stations"][self._dev_id]

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class for the sensor."""
        if self.entity_description.device_class_fn:
            return self.entity_description.device_class_fn(self._xsense_entity)
        return self.entity_description.device_class

    @property
    def icon(self) -> str | None:
        """Return the icon for the sensor."""
        if self.entity_description.icon_fn:
            if icon := self.entity_description.icon_fn(self._xsense_entity):
                return icon
        return self.entity_description.icon

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self._xsense_entity)


class XSenseMQTTConnectedEntity(XSenseBinarySensorEntity):
    """Binary sensors for MQTT connectivity."""

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""

        device = self.coordinator.data["stations"][self._dev_id]
        mqtt_server = self.coordinator.mqtt_server(device.house.mqtt_server)
        return mqtt_server.connected
