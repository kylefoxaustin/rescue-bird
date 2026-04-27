# PX4 airframes & parameter overrides

This directory holds PX4 airframe files and parameter overrides specific to
the rescue-bird scenarios. None ship in the initial scaffold — the sim
container falls back to PX4's stock `gazebo-classic_iris` when nothing is
provided here.

## When you'll want to add something

- **Custom airframe:** if you want to model the actual rescue drone's
  geometry, motor layout, weight, prop pitch. Drop a SYS_AUTOSTART file in
  here and reference it via `PX4_SIM_MODEL` in `docker/.env`.

- **Param overrides:** if mission scenarios need non-default behavior
  (gentler altitude hold for low-altitude search, faster RTL, etc.). PX4
  reads `*.params` files at startup; mount them via the `airframes` volume
  in `docker-compose.yml`.

## Useful references

- PX4 dev guide for adding airframes:
  https://docs.px4.io/main/en/dev_airframes/adding_a_new_frame.html
- PX4 SITL sim integration:
  https://docs.px4.io/main/en/simulation/

## What lives elsewhere

- World files (terrain, obstacles, target placement) → `gazebo/worlds/`
- Mission scenarios (waypoints, target spawns, link events) → `missions/`
- ROS 2 ↔ MAVLink bridge config → handled in `drone_comms` and via mavros
