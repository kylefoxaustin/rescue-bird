# drone_msgs

Custom message interfaces for the rescue-bird stack.

For the initial scaffold we use stock std_msgs / sensor_msgs / geometry_msgs to
keep the build simple. Add typed messages here as the project firms up:

  - `Detection.msg` — bounding box + class + confidence
  - `DetectionArray.msg` — list of detections + frame metadata
  - `MissionPhase.msg` — enum-like phase indicator
  - `LinkStatus.msg` — RTT, loss, throughput
  - `EncodedFrame.msg` — encoded buffer + codec + keyframe flag

Once defined, this package becomes a normal ament_cmake interface package and
the other nodes depend on it.
