# HSL Plugin for TrakBridge

## Description
This plugin integrates real-time vehicle data from HSL, the Helsinki Regional Transport authority (Finland), into TrakBridge. It subscribes to the HSL High-Frequency Positioning (HFP) MQTT broker and generates CoT (Cursor-on-Target) events for trams, subways, trains, ferries and buses.

## Configuration

| Field | Description | Default |
|-------|-------------|---------|
| Route Filter | Comma-separated list of route IDs or passenger route numbers to show. Wildcards supported (e.g., `15,M1,M2,L*`). Leave empty for all routes. | (empty: all) |

## Features
- Real-time tracking of HSL vehicles via the public HFP MQTT feed.
- Mode-aware CoT types: tram, subway/metro, rail, ferry and bus.
- "Anti-jitter" logic to prevent icon jumping when multiple cars in a train report slightly different positions.
- Train composition display: all cars in a train are listed in the CoT infobox.
- Wildcard route filtering matching both internal route IDs and passenger-visible route numbers.

## Example
To follow metro lines M1/M2 and tram line 15, set the route filter to:
```
15,M1,M2
```

## Copyright and License
Copyright Stefan Gofferje
Licensed under the Gnu General Public License Version 3 or higher.

## Changelog

### 0.1.0
- Initial release.
- HFP MQTT subscription with targeted or global topic selection.
- Trip-lock anti-jitter logic and train composition tracking.
- Wildcard route filtering.
