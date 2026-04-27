from setuptools import setup

package_name = "drone_radar"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Kyle",
    description="mmWave radar processing + camera/radar fusion.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "radar_node = drone_radar.radar_node:main",
        ],
    },
)
