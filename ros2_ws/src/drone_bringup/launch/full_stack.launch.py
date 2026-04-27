"""Full-stack bringup: launches every node needed for an end-to-end mission.

Usage from inside a ROS 2 environment:
    ros2 launch drone_bringup full_stack.launch.py

Most users will invoke this via scripts/run_mission.sh, which sets the run
directory, run id, and mission file env vars first.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("model_name",     default_value="edgetam"),
        DeclareLaunchArgument("model_precision", default_value="bf16"),
        DeclareLaunchArgument("link_profile",   default_value="wifi_suburban"),
        DeclareLaunchArgument("encode_codec",   default_value="h265"),
        DeclareLaunchArgument("encode_bitrate_kbps", default_value="6000"),
        DeclareLaunchArgument("radar_format",   default_value="point_cloud"),
        DeclareLaunchArgument("radar_fusion",   default_value="bev_fusion_small"),
        DeclareLaunchArgument("radar_hz",       default_value="20"),
        DeclareLaunchArgument("radar_points",   default_value="1000"),
        DeclareLaunchArgument("isp_input_width",  default_value="1920"),
        DeclareLaunchArgument("isp_input_height", default_value="1080"),
        DeclareLaunchArgument("isp_fps",        default_value="60"),
        DeclareLaunchArgument("isp_csi_lanes",  default_value="4"),
        DeclareLaunchArgument("isp_hdr_exposures", default_value="1"),
        DeclareLaunchArgument("dsp_clock_mhz",  default_value="1100"),
        DeclareLaunchArgument("dsp_simd_lanes", default_value="32"),
        DeclareLaunchArgument("dsp_ops",        default_value="lens_distortion,pyramid_gaussian,optical_flow_init"),

        Node(
            package="drone_telemetry",
            executable="telemetry_node",
            name="drone_telemetry",
            output="screen",
        ),
        Node(
            package="drone_isp",
            executable="isp_node",
            name="drone_isp",
            output="screen",
            additional_env={
                "ISP_INPUT_WIDTH":     LaunchConfiguration("isp_input_width"),
                "ISP_INPUT_HEIGHT":    LaunchConfiguration("isp_input_height"),
                "ISP_FPS":             LaunchConfiguration("isp_fps"),
                "ISP_CSI_LANES":       LaunchConfiguration("isp_csi_lanes"),
                "ISP_HDR_EXPOSURES":   LaunchConfiguration("isp_hdr_exposures"),
            },
        ),
        Node(
            package="drone_dsp",
            executable="dsp_node",
            name="drone_dsp",
            output="screen",
            additional_env={
                "DSP_CLOCK_MHZ":  LaunchConfiguration("dsp_clock_mhz"),
                "DSP_SIMD_LANES": LaunchConfiguration("dsp_simd_lanes"),
                "DSP_OPS":        LaunchConfiguration("dsp_ops"),
            },
        ),
        Node(
            package="drone_perception",
            executable="perception_node",
            name="drone_perception",
            output="screen",
            additional_env={
                "MODEL_NAME":      LaunchConfiguration("model_name"),
                "MODEL_PRECISION": LaunchConfiguration("model_precision"),
            },
        ),
        Node(
            package="drone_vio",
            executable="vio_node",
            name="drone_vio",
            output="screen",
        ),
        Node(
            package="drone_radar",
            executable="radar_node",
            name="drone_radar",
            output="screen",
            additional_env={
                "RADAR_FORMAT": LaunchConfiguration("radar_format"),
                "RADAR_FUSION": LaunchConfiguration("radar_fusion"),
                "RADAR_HZ":     LaunchConfiguration("radar_hz"),
                "RADAR_POINTS": LaunchConfiguration("radar_points"),
            },
        ),
        Node(
            package="drone_video_encode",
            executable="encode_node",
            name="drone_video_encode",
            output="screen",
            additional_env={
                "ENCODE_CODEC":         LaunchConfiguration("encode_codec"),
                "ENCODE_BITRATE_KBPS":  LaunchConfiguration("encode_bitrate_kbps"),
            },
        ),
        Node(
            package="drone_behavior",
            executable="behavior_node",
            name="drone_behavior",
            output="screen",
        ),
        Node(
            package="drone_comms",
            executable="comms_node",
            name="drone_comms",
            output="screen",
            additional_env={
                "LINK_PROFILE": LaunchConfiguration("link_profile"),
            },
        ),
    ])
