from setuptools import setup

package_name = "drone_video_encode"

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
    description="H.264/H.265/AV1 video encode. Maps to dedicated VPU.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "encode_node = drone_video_encode.encode_node:main",
        ],
    },
)
