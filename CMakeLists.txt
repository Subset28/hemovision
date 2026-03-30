cmake_minimum_required(VERSION 3.10)

project(omnisight_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Generate a shared library/DLL for the FFI engine
add_library(core_engine SHARED 
    src/core_engine.cpp
    src/core_engine.h
)

if (WIN32)
    # Windows requires explicit export visibility definition which is handled in the header
    set_target_properties(core_engine PROPERTIES PREFIX "")
endif()
