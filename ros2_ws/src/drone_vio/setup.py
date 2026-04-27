from setuptools import setup

package_name = "drone_vio"

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
    description="Visual-inertial odometry. Maps to GPU+NPU+ARM.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "vio_node = drone_vio.vio_node:main",
        ],
    },
)
