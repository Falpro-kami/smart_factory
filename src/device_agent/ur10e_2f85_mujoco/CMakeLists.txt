cmake_minimum_required(VERSION 3.16)

project(ur10e_2f85_mujoco)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY launch config rviz description
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
