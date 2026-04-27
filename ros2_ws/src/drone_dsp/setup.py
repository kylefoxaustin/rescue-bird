from setuptools import setup

package_name = "drone_dsp"

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
    description="Cadence-class vision DSP workloads.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "dsp_node = drone_dsp.dsp_node:main",
        ],
    },
)
