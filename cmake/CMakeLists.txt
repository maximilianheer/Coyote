# Wrapper to build Coyote library standalone
# This allows ExternalProject_Add to build Coyote as a dependency
cmake_minimum_required(VERSION 3.5)
project(CoyoteWrapper CXX)

# Force library output to build directory root (not lib/ subdirectory)
# This ensures consistent location when used via ExternalProject_Add
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")

include(${CMAKE_CURRENT_SOURCE_DIR}/FindCoyoteSW.cmake)
