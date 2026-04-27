from setuptools import setup

package_name = "drone_isp"

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
    description="Image Signal Processor pipeline.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "isp_node = drone_isp.isp_node:main",
        ],
    },
)
