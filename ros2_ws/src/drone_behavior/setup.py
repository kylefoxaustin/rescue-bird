from setuptools import setup

package_name = "drone_behavior"

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
    description="Mission FSM, tracking, command generation. Maps to ARM application core.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "behavior_node = drone_behavior.behavior_node:main",
        ],
    },
)
