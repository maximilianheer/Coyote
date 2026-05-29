######################################################################################
# This file is part of the Coyote <https://github.com/fpgasystems/Coyote>
# 
# MIT Licence
# Copyright (c) 2025, Systems Group, ETH Zurich
# All rights reserved.
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
######################################################################################

# CMake configuration
cmake_minimum_required(VERSION 3.5)
project(example_13_multi_node_rdma_shien)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(EN_SIM "Enable simulation mode for Coyote" OFF)

if(EN_SIM)
    add_subdirectory(../../../sim/sw ${CMAKE_BINARY_DIR}/coyote)
else()
    add_subdirectory(../../../sw ${CMAKE_BINARY_DIR}/coyote)
endif()

# Add source files
# INSTANCE selects the build target: "node" (default, multi-node pairwise QP setup),
# "client" (legacy 2-node benchmark client), or "server" (legacy 2-node benchmark server).
set(INSTANCE "node" CACHE STRING "Build target: node | client | server")
include_directories("${CMAKE_SOURCE_DIR}/src/include")

find_package(Boost REQUIRED COMPONENTS program_options)

if(INSTANCE STREQUAL "node")
    message("*** Coyote Example 13: Multi-node pairwise RDMA QP setup [node] ***")
    set(EXEC test)
    add_executable(${EXEC} "${CMAKE_SOURCE_DIR}/src/node/main.cpp")
    target_link_libraries(${EXEC} PUBLIC Coyote Boost::program_options)
elseif(INSTANCE STREQUAL "server")
    message("*** Coyote Example 13: RDMA benchmark server (legacy 2-node) ***")
    set(EXEC test)
    add_executable(${EXEC} "${CMAKE_SOURCE_DIR}/src/server/main.cpp")
    target_link_libraries(${EXEC} PUBLIC Coyote Boost::program_options)
elseif(INSTANCE STREQUAL "client")
    message("*** Coyote Example 13: RDMA benchmark client (legacy 2-node) ***")
    set(EXEC test)
    add_executable(${EXEC} "${CMAKE_SOURCE_DIR}/src/client/main.cpp")
    target_link_libraries(${EXEC} PUBLIC Coyote Boost::program_options)
else()
    message(FATAL_ERROR "Unknown INSTANCE='${INSTANCE}'. Use: node | client | server")
endif()
