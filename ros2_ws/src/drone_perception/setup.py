from setuptools import setup

package_name = "drone_perception"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/perception.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Kyle",
    description="Target detection / segmentation node.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "perception_node = drone_perception.perception_node:main",
        ],
    },
)
