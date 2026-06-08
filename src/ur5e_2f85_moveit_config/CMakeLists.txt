cmake_minimum_required(VERSION 3.16)

project(ur5e_2f85_moveit_config)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS scripts/planning_scene_cubes.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
